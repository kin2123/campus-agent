"""P0 加固回归测试。

不依赖 LangChain / MCP 服务，只测本地 SQLite 上的纯业务逻辑：
- thread_id 用户命名空间隔离
- 并发选课不超卖、计数不漂移
- 同一用户并发选同一门课只成功一次
- 审批台账记录最终执行结果

运行：
    cd backend && python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.agent.ledger as ledger_module
from app.agent.session import thread_key
from app.agent.state import snapshot_info
from app.config import settings
from app.models import Base, Course, Enrollment, PendingAction, User
from app.seed import seed_current_semester
from app.services import (
    BusinessError,
    enroll_course,
    get_my_schedule,
    sync_enrollment_counts,
)


class P0HardeningTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False
        )
        ledger_module.SessionLocal = self.Session

        with self.Session() as db:
            course = Course(
                code="T1", name="测试课", teacher_name="T", credits=1,
                capacity=1, weekday=1, start_slot=1, end_slot=2,
            )
            db.add(course)
            users = [
                User(
                    username=f"u{i}", hashed_password="x",
                    name=f"U{i}", role="student",
                )
                for i in range(8)
            ]
            db.add_all(users)
            db.commit()
            self.course_id = course.id
            self.user_ids = [u.id for u in users]

    def tearDown(self) -> None:
        self.engine.dispose()
        try:
            os.unlink(self.path)
        except PermissionError:
            # Windows 下连接释放稍有延迟；临时文件由系统清理即可。
            pass

    def _run_enroll_threads(self, course_id: int, user_ids: list[int]) -> list[str]:
        barrier = threading.Barrier(len(user_ids))
        results: list[str] = []
        lock = threading.Lock()

        def worker(uid: int) -> None:
            db = self.Session()
            try:
                user = db.get(User, uid)
                barrier.wait()
                try:
                    enroll_course(db, user, course_id)
                    out = "ok"
                except BusinessError as exc:
                    out = exc.code
            finally:
                db.close()
            with lock:
                results.append(out)

        threads = [
            threading.Thread(target=worker, args=(uid,)) for uid in user_ids
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    def _run_enroll_pairs(self, pairs: list[tuple[int, int]]) -> list[str]:
        """每个线程用指定的 (user_id, course_id) 并发选课。"""
        barrier = threading.Barrier(len(pairs))
        results: list[str] = []
        lock = threading.Lock()

        def worker(uid: int, course_id: int) -> None:
            db = self.Session()
            try:
                user = db.get(User, uid)
                barrier.wait()
                try:
                    enroll_course(db, user, course_id)
                    out = "ok"
                except BusinessError as exc:
                    out = exc.code
            finally:
                db.close()
            with lock:
                results.append(out)

        threads = [
            threading.Thread(target=worker, args=(uid, course_id))
            for uid, course_id in pairs
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    def test_thread_key_is_user_namespaced_and_idempotent(self) -> None:
        self.assertTrue(thread_key(1, None).startswith("u1:thread-"))
        self.assertEqual(thread_key(1, "abc"), "u1:abc")
        self.assertEqual(thread_key(1, "u1:abc"), "u1:abc")
        self.assertEqual(thread_key(2, "u1:abc"), "u2:u1:abc")
        self.assertEqual(thread_key(2, "u2:abc"), "u2:abc")

    def test_concurrent_enrollment_never_oversells(self) -> None:
        results = self._run_enroll_threads(self.course_id, self.user_ids)

        self.assertEqual(results.count("ok"), 1, results)
        with self.Session() as db:
            rows = db.scalar(
                select(func.count()).select_from(Enrollment).where(
                    Enrollment.course_id == self.course_id,
                    Enrollment.status == "enrolled",
                )
            )
            course = db.get(Course, self.course_id)
            self.assertEqual(rows, 1)
            self.assertEqual(course.enrolled_count, 1)

    def test_same_user_concurrent_enrollment_only_once(self) -> None:
        with self.Session() as db:
            course = Course(
                code="T2", name="同人并发", teacher_name="T", credits=1,
                capacity=3, weekday=2, start_slot=1, end_slot=2,
            )
            db.add(course)
            db.commit()
            course_id = course.id

        results = self._run_enroll_threads(course_id, [self.user_ids[0]] * 5)

        self.assertEqual(results.count("ok"), 1, results)
        with self.Session() as db:
            rows = db.scalar(
                select(func.count()).select_from(Enrollment).where(
                    Enrollment.course_id == course_id,
                    Enrollment.status == "enrolled",
                )
            )
            course = db.get(Course, course_id)
            self.assertEqual(rows, 1)
            self.assertEqual(course.enrolled_count, 1)

    def test_sync_enrollment_counts_repairs_drift(self) -> None:
        self._run_enroll_threads(self.course_id, self.user_ids)
        with self.Session() as db:
            course = db.get(Course, self.course_id)
            course.enrolled_count = 99
            db.commit()
            sync_enrollment_counts(db)
            self.assertEqual(db.get(Course, self.course_id).enrolled_count, 1)

    def test_same_user_concurrent_courses_cannot_bypass_limits(self) -> None:
        """同一学生并发选两门时间相同、各 20 学分的课，只能成功一门。"""
        with self.Session() as db:
            first = Course(
                code="T3A", name="并发课A", teacher_name="T", credits=20,
                capacity=5, weekday=3, start_slot=1, end_slot=2,
            )
            second = Course(
                code="T3B", name="并发课B", teacher_name="T", credits=20,
                capacity=5, weekday=3, start_slot=1, end_slot=2,
            )
            db.add_all([first, second])
            db.commit()
            pairs = [(self.user_ids[0], first.id), (self.user_ids[0], second.id)]

        results = self._run_enroll_pairs(pairs)

        self.assertEqual(results.count("ok"), 1, results)
        rejected = [r for r in results if r != "ok"]
        self.assertEqual(len(rejected), 1, results)
        self.assertIn(rejected[0], {"TIME_CONFLICT", "CREDIT_LIMIT_EXCEEDED"}, results)

        with self.Session() as db:
            schedule = get_my_schedule(db, db.get(User, self.user_ids[0]))
            self.assertEqual(len(schedule), 1)
            total = sum(float(course.credits) for course in schedule)
            self.assertLessEqual(total, settings.max_credits_per_semester)

    def test_seed_current_semester_preserves_user_state(self) -> None:
        """启动 seed 只补缺，不能把退课恢复成在读，也不能清空已有成绩。"""
        with self.Session() as db:
            student = User(
                username="20230101", hashed_password="x", name="张思远", role="student"
            )
            dropped_course = Course(code="CS202", name="数据结构", teacher_name="T")
            completed_course = Course(code="CS205", name="计算机网络", teacher_name="T")
            db.add_all([student, dropped_course, completed_course])
            db.commit()
            db.add_all(
                [
                    Enrollment(
                        user_id=student.id, course_id=dropped_course.id, status="dropped"
                    ),
                    Enrollment(
                        user_id=student.id, course_id=completed_course.id,
                        status="completed", score=88.0,
                    ),
                ]
            )
            db.commit()
            student_id = student.id
            dropped_id = dropped_course.id
            completed_id = completed_course.id

            seed_current_semester(db)

            dropped = db.scalar(
                select(Enrollment).where(
                    Enrollment.user_id == student_id,
                    Enrollment.course_id == dropped_id,
                )
            )
            completed = db.scalar(
                select(Enrollment).where(
                    Enrollment.user_id == student_id,
                    Enrollment.course_id == completed_id,
                )
            )
            self.assertEqual(dropped.status, "dropped")
            self.assertIsNone(dropped.score)
            self.assertEqual(completed.status, "completed")
            self.assertEqual(completed.score, 88.0)

    def test_snapshot_info_rejects_checkpoint_dict(self) -> None:
        """checkpointer.aget() 返回的是 checkpoint 字典，不能当成有中断的会话。"""
        self.assertEqual(
            snapshot_info({"id": "cp1", "channel_values": {}}),
            {"exists": False},
        )

    def test_snapshot_info_detects_pending_interrupt(self) -> None:
        snapshot = SimpleNamespace(
            created_at="2026-11-02T08:00:00Z",
            next=("tools",),
            tasks=(SimpleNamespace(interrupts=(object(),)),),
            interrupts=(),
        )
        info = snapshot_info(snapshot)
        self.assertTrue(info["exists"])
        self.assertTrue(info["has_interrupt"])

    def test_snapshot_info_completed_has_no_interrupt(self) -> None:
        snapshot = SimpleNamespace(
            created_at="2026-11-02T08:00:00Z",
            next=(),
            tasks=(),
            interrupts=(),
        )
        info = snapshot_info(snapshot)
        self.assertTrue(info["exists"])
        self.assertFalse(info["has_interrupt"])

    def test_ledger_records_final_result(self) -> None:
        interrupt = (
            "event: interrupt\n"
            'data: {"thread_id":"u1:t","actions":['
            '{"name":"campus_enroll_course","args":{"course_code":"CS202"},"description":"选课"},'
            '{"name":"campus_drop_course","args":{"course_code":"CS201"},"description":"退课"}]}\n\n'
        )
        ledger_module.record_pending_actions("u1:t", self.user_ids[0], interrupt)

        with self.Session() as db:
            rows = db.scalars(
                select(PendingAction).order_by(PendingAction.id)
            ).all()
            self.assertEqual(len(rows), 2)
            enroll_id, drop_id = rows[0].id, rows[1].id
            self.assertTrue(all(row.status == "pending" for row in rows))

        ledger = ledger_module.ResumeLedger("u1:t", self.user_ids[0])
        ledger.track_approved(
            [
                (enroll_id, "campus_enroll_course"),
                (drop_id, "campus_drop_course"),
            ]
        )
        ledger.on_event(
            'event: tool_result\n'
            'data: {"name":"campus_enroll_course","ok":true,"content":"选课成功"}\n\n'
        )
        ledger.on_event(
            'event: tool_result\n'
            'data: {"name":"campus_drop_course","ok":false,'
            '"content":"退课未成功（SCORE_ARCHIVED）"}\n\n'
        )
        ledger.flush()

        with self.Session() as db:
            enroll_row = db.get(PendingAction, enroll_id)
            drop_row = db.get(PendingAction, drop_id)
            self.assertEqual(enroll_row.result, "SUCCESS")
            self.assertEqual(drop_row.result, "FAILED")
            self.assertIn("SCORE_ARCHIVED", drop_row.error or "")
            self.assertIsNotNone(enroll_row.executed_at)

    def test_ledger_skips_rejected_tool_message(self) -> None:
        """同名工具一项拒绝、一项批准时，拒绝的 ToolMessage 不能吃掉批准行。"""
        with self.Session() as db:
            rejected = PendingAction(
                thread_id="u1:t3", user_id=self.user_ids[0],
                tool_name="campus_enroll_course", args="{}",
                status="rejected", result="REJECTED",
            )
            approved = PendingAction(
                thread_id="u1:t3", user_id=self.user_ids[0],
                tool_name="campus_enroll_course", args="{}", status="approved",
            )
            db.add_all([rejected, approved])
            db.commit()
            rejected_id, approved_id = rejected.id, approved.id

        ledger = ledger_module.ResumeLedger("u1:t3", self.user_ids[0])
        ledger.track_approved([(approved_id, "campus_enroll_course")])
        ledger.on_event(
            'event: tool_result\n'
            'data: {"name":"campus_enroll_course","ok":false,"decision":"reject",'
            '"content":"用户拒绝"}\n\n'
        )
        ledger.on_event(
            'event: tool_result\n'
            'data: {"name":"campus_enroll_course","ok":true,"decision":"approve",'
            '"content":"选课成功"}\n\n'
        )
        ledger.flush()

        with self.Session() as db:
            self.assertEqual(db.get(PendingAction, rejected_id).result, "REJECTED")
            self.assertEqual(db.get(PendingAction, approved_id).result, "SUCCESS")

    def test_ledger_marks_approved_but_unexecuted(self) -> None:
        with self.Session() as db:
            row = PendingAction(
                thread_id="u1:t2", user_id=self.user_ids[0],
                tool_name="campus_enroll_course", args="{}", status="approved",
            )
            db.add(row)
            db.commit()
            row_id = row.id

        ledger = ledger_module.ResumeLedger("u1:t2", self.user_ids[0])
        ledger.track_approved([(row_id, "campus_enroll_course")])
        ledger.flush()

        with self.Session() as db:
            row = db.get(PendingAction, row_id)
            self.assertEqual(row.result, "NOT_EXECUTED")


if __name__ == "__main__":
    unittest.main()
