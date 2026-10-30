-- ============================================================
-- 小微企业授信智能预审系统 - MySQL 8.0 数据库结构
-- 字符集：utf8mb4 / utf8mb4_unicode_ci
-- 引擎：InnoDB
-- 说明：与 app/models 下的 SQLAlchemy 模型保持一致
-- ============================================================

CREATE DATABASE IF NOT EXISTS `sme_credit`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `sme_credit`;

-- ------------------------------------------------------------
-- 用户登录信息表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `id`              INT          NOT NULL AUTO_INCREMENT,
  `username`        VARCHAR(50)  NOT NULL                COMMENT '登录用户名',
  `full_name`       VARCHAR(50)  NOT NULL                COMMENT '姓名',
  `role`            VARCHAR(20)  NOT NULL DEFAULT 'manager' COMMENT '角色：manager/risk/admin',
  `hashed_password` VARCHAR(255) NOT NULL                COMMENT '加密密码（PBKDF2-SHA256）',
  `is_active`       TINYINT(1)   NOT NULL DEFAULT 1      COMMENT '是否启用',
  `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_users_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户登录信息';

-- ------------------------------------------------------------
-- 授信申请表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `applications` (
  `id`           INT           NOT NULL AUTO_INCREMENT,
  `app_no`       VARCHAR(32)   NOT NULL                COMMENT '申请编号',
  `company_name` VARCHAR(200)  NOT NULL                COMMENT '企业名称',
  `credit_code`  VARCHAR(18)   NULL                    COMMENT '统一社会信用代码',
  `amount`       DECIMAL(12,2) NOT NULL                COMMENT '申请金额（万元）',
  `product`      VARCHAR(100)  NOT NULL                COMMENT '贷款产品',
  `status`       VARCHAR(20)   NOT NULL DEFAULT 'check' COMMENT '状态：check/supplement/manual/risk/approved/rejected',
  `manager_name` VARCHAR(50)   NULL                    COMMENT '客户经理',
  `sla_deadline` DATETIME      NULL                    COMMENT '时效截止时间',
  `ai_summary`   TEXT          NULL                    COMMENT 'AI 摘要',
  `supplement_note`   VARCHAR(500) NULL                COMMENT '退回补件说明（人工/风控退回时写入）',
  `supplement_source` VARCHAR(10)  NULL                COMMENT '补件来源：manual=人工复核退回，risk=风控退回',
  `created_at`   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_applications_app_no` (`app_no`),
  KEY `ix_applications_company_name` (`company_name`),
  KEY `ix_applications_credit_code` (`credit_code`),
  KEY `ix_applications_status` (`status`),
  CONSTRAINT `ck_applications_status` CHECK (`status` IN ('check', 'supplement', 'manual', 'risk', 'approved', 'rejected'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='授信申请';

-- ------------------------------------------------------------
-- 申请材料表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `materials` (
  `id`          INT          NOT NULL AUTO_INCREMENT,
  `app_id`      INT          NOT NULL                COMMENT '申请 ID',
  `category`    VARCHAR(100) NOT NULL                COMMENT '材料类别编码',
  `file_name`   VARCHAR(255) NOT NULL                COMMENT '文件名',
  `file_url`    VARCHAR(500) NULL                    COMMENT '存储地址',
  `file_size`   INT          NULL                    COMMENT '文件大小（字节）',
  `version`     VARCHAR(16)  NOT NULL DEFAULT 'v1.0' COMMENT '材料版本',
  `status`      VARCHAR(20)  NOT NULL DEFAULT 'pending' COMMENT '抽取状态：pending/ok/low/none',
  `confidence`  DECIMAL(4,3) NULL                    COMMENT 'AI 分类置信度（0~1）',
  `reason`        TEXT         NULL               COMMENT 'AI 分类依据',
  `ocr_text`      TEXT         NULL               COMMENT 'OCR 抽取文本（复用于分类与预审，避免重复识别）',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_materials_app_id` (`app_id`),
  CONSTRAINT `fk_materials_app_id` FOREIGN KEY (`app_id`)
    REFERENCES `applications` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_materials_status` CHECK (`status` IN ('pending', 'ok', 'low', 'none'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='申请材料';

-- ------------------------------------------------------------
-- AI 预审报告表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ai_reports` (
  `id`            INT          NOT NULL AUTO_INCREMENT,
  `app_id`        INT          NOT NULL           COMMENT '申请 ID',
  `version`       VARCHAR(16)  NOT NULL DEFAULT 'v1' COMMENT '报告版本',
  `rule_version`  VARCHAR(32)  NULL               COMMENT '规则版本',
  `rule_snapshot` JSON         NULL               COMMENT '规则文件快照',
  `conclusion`    VARCHAR(20)  NOT NULL           COMMENT '结论：pass/attention/forbidden/manual',
  `summary`       TEXT         NULL               COMMENT '预审结论摘要',
  `pass_rate`     DECIMAL(5,2) NULL               COMMENT '预估通过率（%）',
  `rule_results`  JSON         NULL               COMMENT '准入规则逐条匹配结果',
  `risk_signals`  JSON         NULL               COMMENT '风险信号汇总',
  `conflicts`     JSON         NULL               COMMENT '低置信/冲突项',
  `completeness`  JSON         NULL               COMMENT '材料完整性分析结果',
  `consistency`   JSON         NULL               COMMENT '材料一致性分析结果',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_ai_reports_app_id` (`app_id`),
  CONSTRAINT `fk_ai_reports_app_id` FOREIGN KEY (`app_id`)
    REFERENCES `applications` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_ai_reports_conclusion` CHECK (`conclusion` IN ('pass', 'attention', 'forbidden', 'manual'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 预审报告';

-- ------------------------------------------------------------
-- 人工复核记录表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `manual_reviews` (
  `id`               INT         NOT NULL AUTO_INCREMENT,
  `app_id`           INT         NOT NULL           COMMENT '申请 ID',
  `reviewer`         VARCHAR(50) NOT NULL           COMMENT '复核人',
  `decision`         VARCHAR(20) NOT NULL           COMMENT '结论：pass=通过转风控，reject=退回补件，deny=否决',
  `checklist_result` JSON        NULL               COMMENT '逐项复核结果',
  `comment`          TEXT        NULL               COMMENT '复核意见',
  `created_at`       DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_manual_reviews_app_id` (`app_id`),
  CONSTRAINT `fk_manual_reviews_app_id` FOREIGN KEY (`app_id`)
    REFERENCES `applications` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_manual_reviews_decision` CHECK (`decision` IN ('pass', 'conditional', 'reject', 'further', 'deny'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='人工复核记录';

-- ------------------------------------------------------------
-- 风控复核记录表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `risk_reviews` (
  `id`         INT          NOT NULL AUTO_INCREMENT,
  `app_id`     INT          NOT NULL           COMMENT '申请 ID',
  `reviewer`   VARCHAR(50)  NOT NULL           COMMENT '风控人员',
  `decision`   VARCHAR(20)  NOT NULL           COMMENT '结论：pass=通过审批，reject=退回补件，deny=否决',
  `opinion`    TEXT         NOT NULL           COMMENT '风控复核意见',
  `mitigation` VARCHAR(500) NULL               COMMENT '风险缓释条件',
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_risk_reviews_app_id` (`app_id`),
  CONSTRAINT `fk_risk_reviews_app_id` FOREIGN KEY (`app_id`)
    REFERENCES `applications` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_risk_reviews_decision` CHECK (`decision` IN ('pass', 'conditional', 'reject', 'further', 'deny'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='风控复核记录';
