-- ============================================================
-- 学生公寓报修系统 —— MySQL 数据库建表脚本
-- 适配 Navicat 导入，数据库名格式：你的姓名拼音_505
-- 三张独立表：students、workers、admins，支持同一邮箱登录不同角色
-- ============================================================

-- 【学生表】
CREATE TABLE IF NOT EXISTS students (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '学生ID',
    name VARCHAR(50) NOT NULL COMMENT '姓名',
    student_no VARCHAR(20) NOT NULL DEFAULT 'js23150301' COMMENT '学号，格式：js+八位数字',
    email VARCHAR(100) NOT NULL COMMENT '邮箱',
    password_hash VARCHAR(256) NOT NULL COMMENT '密码哈希',
    phone VARCHAR(20) COMMENT '手机号',
    created_at DATETIME NOT NULL COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生表';

-- 【维修工表】
CREATE TABLE IF NOT EXISTS workers (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '维修工ID',
    name VARCHAR(50) NOT NULL COMMENT '姓名',
    email VARCHAR(100) NOT NULL COMMENT '邮箱',
    password_hash VARCHAR(256) NOT NULL COMMENT '密码哈希',
    worker_no VARCHAR(20) NOT NULL COMMENT '工号',
    phone VARCHAR(20) COMMENT '手机号',
    created_at DATETIME NOT NULL COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='维修工表';

-- 【管理员表】
CREATE TABLE IF NOT EXISTS admins (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '管理员ID',
    name VARCHAR(50) NOT NULL COMMENT '姓名',
    admin_no VARCHAR(20) NOT NULL DEFAULT 'MX001' COMMENT '管理工号',
    email VARCHAR(100) NOT NULL COMMENT '邮箱',
    password_hash VARCHAR(256) NOT NULL COMMENT '密码哈希',
    secret_key VARCHAR(64) COMMENT 'MX001 专属安全密钥',
    phone VARCHAR(20) COMMENT '手机号',
    created_at DATETIME NOT NULL COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='管理员表';

-- 【邮箱验证码表】
CREATE TABLE IF NOT EXISTS email_codes (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '验证码记录ID',
    email VARCHAR(100) NOT NULL COMMENT '接收验证码的邮箱',
    purpose VARCHAR(50) NOT NULL COMMENT '用途标识',
    code_hash VARCHAR(256) NOT NULL COMMENT '验证码哈希值',
    expire_at DATETIME NOT NULL COMMENT '过期时间',
    used TINYINT NOT NULL DEFAULT 0 COMMENT '是否已使用',
    created_at DATETIME NOT NULL COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='邮箱验证码表';

-- 【报修工单表】
CREATE TABLE IF NOT EXISTS repair_orders (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '工单ID',
    student_id INT NOT NULL COMMENT '报修学生ID',
    student_no VARCHAR(20) NOT NULL COMMENT '报修学生学号',
    worker_id INT COMMENT '维修工ID',
    dorm_building VARCHAR(50) NOT NULL COMMENT '宿舍楼',
    room_no VARCHAR(20) NOT NULL COMMENT '房间号',
    category VARCHAR(50) NOT NULL COMMENT '故障类别',
    description TEXT NOT NULL COMMENT '故障详细描述',
    status VARCHAR(30) NOT NULL DEFAULT 'pending_review' COMMENT '状态',
    audit_note TEXT COMMENT '审核意见',
    result_note TEXT COMMENT '维修结果说明',
    result_image VARCHAR(255) COMMENT '维修结果图片路径',
    created_at DATETIME NOT NULL COMMENT '工单创建时间',
    reviewed_at DATETIME COMMENT '审核时间',
    accepted_at DATETIME COMMENT '接单时间',
    finished_at DATETIME COMMENT '完成时间',
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (worker_id) REFERENCES workers(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='报修工单表';

-- ============================================================
-- 【已有数据库升级】如需为已有表添加 result_image 字段，执行以下语句：
-- ALTER TABLE repair_orders ADD COLUMN result_image VARCHAR(255) COMMENT '维修结果图片路径';
-- ============================================================

-- ============================================================
-- 【默认数据】由 app.py 的 init_db() 函数在程序启动时自动插入
-- 程序会使用 generate_password_hash() 生成真实的密码哈希
-- 密码明文：123123
-- ============================================================
