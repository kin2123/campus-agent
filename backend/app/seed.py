"""种子数据：课程、学生、教师、历史成绩。

幂等设计：按唯一键判断是否已存在，重复运行不会产生重复数据。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Course, Enrollment, User

SEMESTER = "2026-2027-1"
DEMO_PASSWORD = "123456"

# (code, name, teacher, credits, capacity, weekday, start, end, location, category,
#  exam_type, prereq, description)
COURSES: list[tuple] = [
    ("CS201", "程序设计基础", "陈立群", 4.0, 60, 1, 1, 2, "信息楼 A301", "专业必修", "考试", "",
     "以 C/C++ 为教学语言，讲授变量、流程控制、函数、数组、指针与结构体，是后续全部专业课程的地基。"),
    ("CS202", "数据结构", "王海宁", 4.0, 55, 2, 3, 4, "信息楼 A302", "专业必修", "考试", "CS201",
     "线性表、栈与队列、树与二叉树、图、查找与排序。要求能用代码实现常见数据结构并分析时间复杂度。"),
    ("CS203", "计算机组成原理", "李明远", 4.0, 50, 3, 1, 2, "信息楼 A303", "专业必修", "考试", "",
     "讲授数制与编码、运算器、存储系统、指令系统、CPU 数据通路与流水线，配合 Verilog 实验。"),
    ("CS204", "操作系统", "张伟", 4.0, 50, 4, 3, 4, "信息楼 A304", "专业必修", "考试", "CS202,CS203",
     "进程与线程、调度算法、同步互斥、死锁、内存管理、文件系统与 I/O。含 xv6 内核实验。"),
    ("CS205", "计算机网络", "刘思远", 3.0, 60, 4, 5, 6, "信息楼 A305", "专业必修", "考试", "",
     "OSI 与 TCP/IP 体系、链路层与以太网、IP 路由、TCP 拥塞控制、HTTP/DNS，配合 socket 编程实验。"),
    ("CS206", "数据库系统原理", "赵敏", 3.0, 55, 4, 7, 8, "信息楼 A306", "专业必修", "考试", "CS202",
     "关系模型、SQL、范式理论、索引与查询优化、事务与并发控制、故障恢复。含 MySQL 实践。"),
    ("CS207", "软件工程", "孙晓丹", 3.0, 60, 5, 1, 2, "信息楼 A307", "专业必修", "考查", "CS202",
     "软件过程模型、需求工程、结构化与面向对象设计、UML、测试方法、项目管理与版本控制。"),
    ("CS208", "编译原理", "周建国", 3.0, 45, 5, 3, 4, "信息楼 A308", "专业必修", "考试", "CS202,CS203",
     "词法分析、语法分析（LL/LR）、语法制导翻译、语义分析、中间代码生成与优化。"),
    ("CS209", "人工智能导论", "吴静", 3.0, 70, 5, 5, 6, "信息楼 B201", "专业必修", "考试", "",
     "搜索与博弈、知识表示与推理、机器学习基础、神经网络入门、智能体与强化学习初步。"),
    ("CS210", "算法设计与分析", "郑凯", 3.0, 50, 5, 7, 8, "信息楼 A302", "专业必修", "考试", "CS202",
     "分治、动态规划、贪心、回溯、分支限界、NP 完全性理论与近似算法。"),
    ("CS214", "机器学习", "吴静", 3.0, 45, 6, 1, 2, "信息楼 B402", "专业必修", "考试", "CS209",
     "线性回归、逻辑回归、决策树、集成学习、SVM、聚类、降维与模型评估方法。"),
    ("CS301", "深度学习", "林浩", 3.0, 40, 2, 5, 6, "信息楼 B402", "专业选修", "考查", "CS214",
     "反向传播、CNN、RNN/LSTM、Attention 与 Transformer、生成模型与训练调优实战。适合方向一。"),
    ("CS302", "自然语言处理", "林浩", 2.0, 40, 3, 5, 6, "信息楼 B403", "专业选修", "考查", "CS214",
     "词向量、序列标注、句法分析、文本分类、机器翻译与大语言模型基础应用。"),
    ("CS303", "计算机视觉", "何雅琴", 3.0, 40, 4, 7, 8, "信息楼 B403", "专业选修", "考查", "CS214",
     "图像滤波、特征检测、图像分类、目标检测与分割、三维重建入门。"),
    ("CS304", "知识图谱", "何雅琴", 2.0, 35, 5, 9, 10, "信息楼 B403", "专业选修", "考查", "",
     "本体建模、RDF/OWL、知识抽取、图数据库 Neo4j、图谱推理与问答应用。"),
    ("CS311", "分布式系统", "刘思远", 3.0, 45, 2, 7, 8, "信息楼 A305", "专业选修", "考试", "CS204,CS205",
     "一致性模型、CAP、共识算法（Paxos/Raft）、分布式存储与计算框架。适合方向二。"),
    ("CS312", "云计算技术", "刘思远", 2.0, 50, 3, 7, 8, "信息楼 A305", "专业选修", "考查", "CS205",
     "虚拟化、容器与 Docker、Kubernetes 编排、云原生架构与服务网格。"),
    ("CS313", "网络安全", "周建国", 3.0, 45, 5, 5, 6, "信息楼 B305", "专业选修", "考试", "CS205",
     "密码学基础、身份认证、Web 安全（SQL 注入/XSS/CSRF）、渗透测试与防御体系。"),
    ("CS314", "嵌入式系统", "李明远", 3.0, 40, 6, 3, 4, "信息楼 B305", "专业选修", "考查", "CS203",
     "ARM 架构、GPIO/中断/定时器、RTOS 原理、驱动开发与物联网应用。"),
    ("CS321", "软件测试", "孙晓丹", 2.0, 50, 3, 9, 10, "信息楼 A307", "专业选修", "考查", "CS207",
     "黑盒白盒测试、单元测试、自动化测试框架、性能测试与缺陷管理。适合方向三。"),
    ("CS322", "软件项目管理", "孙晓丹", 2.0, 50, 4, 9, 10, "信息楼 A307", "专业选修", "考查", "",
     "敏捷与 Scrum、需求与范围管理、进度与成本估算、风险管理与团队协作。"),
    ("CS323", "DevOps 实战", "郑凯", 2.0, 40, 6, 7, 8, "信息楼 A305", "专业选修", "考查", "CS312",
     "CI/CD 流水线、Git 工作流、Jenkins/GitLab CI、监控告警与容器化部署实战。"),
    ("CS331", "数据挖掘", "赵敏", 3.0, 45, 3, 3, 4, "信息楼 A306", "专业选修", "考查", "CS206",
     "关联规则、聚类、分类、异常检测、特征工程与数据预处理。适合方向四。"),
    ("CS332", "数据可视化", "何雅琴", 2.0, 45, 5, 3, 4, "信息楼 B403", "专业选修", "考查", "",
     "可视化设计原则、ECharts/D3 实践、交互式图表与数据故事讲述。"),
    ("CS333", "数据仓库与 OLAP", "赵敏", 2.0, 40, 6, 5, 6, "信息楼 A306", "专业选修", "考查", "CS206",
     "维度建模、星型与雪花模型、ETL 流程、OLAP 立方体与查询优化。"),
    ("GE101", "马克思主义基本原理", "高志强", 3.0, 120, 1, 3, 4, "文科楼 201", "通识必修", "考试", "",
     "马克思主义哲学、政治经济学与科学社会主义基本原理。"),
    ("GE102", "大学英语（三）", "Emily Chen", 3.0, 60, 2, 1, 2, "外语楼 305", "通识必修", "考试", "",
     "学术英语读写与听说训练，含四级词汇强化与学术写作规范。"),
    ("GE103", "概率论与数理统计", "钱伟", 3.0, 90, 3, 1, 2, "理科楼 101", "学科基础", "考试", "",
     "随机事件与概率、随机变量分布、数字特征、大数定律、参数估计与假设检验。"),
    ("GE104", "大学体育（五）", "徐峰", 1.0, 80, 4, 9, 10, "体育馆", "通识必修", "考查", "",
     "篮球、羽毛球、体能与体质健康测试。"),
    ("GE201", "艺术鉴赏", "苏文清", 2.0, 100, 4, 5, 6, "文科楼 305", "通识选修", "考查", "",
     "中外美术、音乐、建筑与影视作品鉴赏，含 4 次校外美术馆实践。满足艺术类学分要求。"),
    ("GE202", "创新创业基础", "孙晓丹", 2.0, 80, 6, 9, 10, "文科楼 302", "通识选修", "考查", "",
     "商业计划书撰写、商业模式画布、路演技巧与创业案例分析。满足创新创业类学分要求。"),
    ("GE203", "科技论文写作", "钱伟", 2.0, 60, 5, 9, 10, "文科楼 303", "通识选修", "考查", "",
     "学术论文结构、文献检索与管理、图表规范、投稿流程与学术道德。"),
]

STUDENTS: list[tuple] = [
    ("20230101", "张思远", "计算机科学与技术", "2023", "计科 2301"),
    ("20230102", "李佳琪", "计算机科学与技术", "2023", "计科 2301"),
    ("20230103", "王梓涵", "计算机科学与技术", "2023", "计科 2302"),
]

TEACHERS: list[tuple] = [
    ("T2001", "王海宁", "计算机科学与技术", None, None),
    ("T2002", "吴静", "计算机科学与技术", None, None),
]


def seed(db: Session) -> dict[str, int]:
    # 延迟导入：seed_current_semester / seed_history 是纯数据函数，
    # 不需要为了它们把 JWT/bcrypt 依赖拉进模块导入阶段。
    from .security import hash_password

    created = {"courses": 0, "users": 0, "enrollments": 0}

    # ---------- 课程 ----------
    for row in COURSES:
        (code, name, teacher, credits, capacity, weekday, start, end,
         location, category, exam_type, prereq, desc) = row
        exists = db.scalar(select(Course).where(Course.code == code))
        if exists:
            continue
        db.add(
            Course(
                code=code, name=name, teacher_name=teacher, credits=credits,
                capacity=capacity, semester=SEMESTER, category=category,
                weekday=weekday, start_slot=start, end_slot=end, location=location,
                exam_type=exam_type, prerequisite_codes=prereq, description=desc,
            )
        )
        created["courses"] += 1

    # ---------- 管理员 ----------
    if not db.scalar(select(User).where(User.username == "admin")):
        db.add(
            User(
                username="admin", hashed_password=hash_password(DEMO_PASSWORD),
                name="教务管理员", role="admin",
            )
        )
        created["users"] += 1

    # ---------- 教师 ----------
    for username, name, major, grade, class_name in TEACHERS:
        if db.scalar(select(User).where(User.username == username)):
            continue
        db.add(
            User(
                username=username, hashed_password=hash_password(DEMO_PASSWORD),
                name=name, role="teacher", student_no=username, major=major,
            )
        )
        created["users"] += 1

    # ---------- 学生 ----------
    for student_no, name, major, grade, class_name in STUDENTS:
        if db.scalar(select(User).where(User.username == student_no)):
            continue
        db.add(
            User(
                username=student_no, hashed_password=hash_password(DEMO_PASSWORD),
                name=name, role="student", student_no=student_no, major=major,
                grade=grade, class_name=class_name,
            )
        )
        created["users"] += 1

    db.commit()
    return created


def seed_current_semester(db: Session) -> dict[str, int]:
    """给主账号造几门**本学期在读**的课。

    为什么必须区分「在读」和「已修完」：
    只造历史成绩的话，`/api/me/schedule` 是空的 —— 课表周视图网格
    （这个项目最直观的一个界面）会渲染成一片空白，演示效果很差。
    而如果把历史成绩也记成 enrolled，它们又会混进课表。

    所以两种状态各造一批：`completed` 进成绩单，`enrolled` 进课表。
    选课刻意避开时间冲突，并覆盖周一到周六，让网格看起来是满的。

    只在记录不存在时补充；已存在的记录一律保持原样，
    否则重启后端会把用户退掉的课恢复、把已有成绩清空。
    """
    student = db.scalar(select(User).where(User.username == "20230101"))
    if student is None:
        return {"current": 0}

    # (课程代码, 是否符合先修要求) —— 这几门都是无先修或先修已通过的
    current = ["CS202", "CS205", "CS209", "GE202"]
    added = 0
    for code in current:
        course = db.scalar(select(Course).where(Course.code == code))
        if course is None:
            continue
        record = db.scalar(
            select(Enrollment).where(
                Enrollment.user_id == student.id, Enrollment.course_id == course.id
            )
        )
        if record is not None:
            # 只补缺，不覆盖。用户可能已经退课或已有成绩，
            # 启动时把它们改回 enrolled 会凭空恢复课程、清空成绩。
            continue
        db.add(
            Enrollment(
                user_id=student.id, course_id=course.id,
                status="enrolled", source="WEB",
            )
        )
        added += 1
    db.commit()
    return {"current": added}


def seed_history(db: Session) -> dict[str, int]:
    """给主账号「张思远」造一批已出成绩的历史课程。

    这些成绩有两个作用：
    ① 让「查成绩」类问题有真实数据；
    ② 作为先修课判定的依据（比如已通过 CS201 才能选 CS202）。
    """
    student = db.scalar(select(User).where(User.username == "20230101"))
    if student is None:
        return {"history": 0}

    history = [
        ("CS201", 88.0), ("CS203", 79.0), ("GE101", 82.0),
        ("GE102", 74.0), ("GE103", 91.0), ("GE104", 85.0),
    ]
    added = 0
    for code, score in history:
        course = db.scalar(select(Course).where(Course.code == code))
        if course is None:
            continue
        record = db.scalar(
            select(Enrollment).where(
                Enrollment.user_id == student.id, Enrollment.course_id == course.id
            )
        )
        if record is not None:
            continue
        db.add(
            Enrollment(
                user_id=student.id, course_id=course.id,
                status="completed", score=score, source="WEB",
            )
        )
        added += 1
    db.commit()
    return {"history": added}
