-- AgentLens MySQL schema reference.
-- The backend can also run on SQLite. The canonical DDL lives in
-- backend/knowflow/db_schema.py; keep this document in sync when schema
-- fields or tables change.

CREATE TABLE IF NOT EXISTS model_config (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  name VARCHAR(100) NOT NULL,
  provider VARCHAR(50) NOT NULL,
  model_type VARCHAR(30) NOT NULL,
  base_url VARCHAR(255) NOT NULL,
  api_key_cipher TEXT,
  model_name VARCHAR(100) NOT NULL,
  temperature DECIMAL(3,2) DEFAULT NULL,
  top_p DECIMAL(3,2) DEFAULT NULL,
  max_tokens INT DEFAULT NULL,
  is_default TINYINT DEFAULT 0,
  status VARCHAR(30) DEFAULT 'untested',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS knowledge_base (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  name VARCHAR(100) NOT NULL,
  description VARCHAR(500),
  embedding_model_config_id BIGINT NOT NULL,
  document_count INT DEFAULT 0,
  chunk_count INT DEFAULT 0,
  status VARCHAR(30) DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS document (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  knowledge_base_id BIGINT NOT NULL,
  filename VARCHAR(255) NOT NULL,
  file_type VARCHAR(20),
  file_size BIGINT,
  file_md5 VARCHAR(64) NOT NULL,
  storage_path VARCHAR(500),
  parse_status VARCHAR(30) DEFAULT 'pending',
  chunk_count INT DEFAULT 0,
  error_message TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_kb_md5 (knowledge_base_id, file_md5),
  KEY idx_document_kb (knowledge_base_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS document_chunk (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  knowledge_base_id BIGINT NOT NULL,
  document_id BIGINT NOT NULL,
  chunk_index INT NOT NULL,
  chunk_text LONGTEXT,
  vector_id VARCHAR(100) NOT NULL,
  token_count INT DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_chunk_kb_doc (knowledge_base_id, document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_session (
  id VARCHAR(64) PRIMARY KEY,
  user_id BIGINT,
  title VARCHAR(255),
  knowledge_base_id BIGINT,
  chat_model_config_id BIGINT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_message (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  session_id VARCHAR(64) NOT NULL,
  role VARCHAR(20) NOT NULL,
  content LONGTEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_message_session_time (session_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS message_reference (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  message_id BIGINT NOT NULL,
  document_id BIGINT NOT NULL,
  chunk_id BIGINT NOT NULL,
  score DECIMAL(6,4),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS retrieval_run (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  knowledge_base_id BIGINT NOT NULL,
  message_id BIGINT DEFAULT NULL,
  query TEXT NOT NULL,
  top_k INT DEFAULT 5,
  status VARCHAR(30) DEFAULT 'success',
  hit_count INT DEFAULT 0,
  max_score DECIMAL(6,4) DEFAULT 0,
  quality_level VARCHAR(30) DEFAULT 'no_match',
  quality_json JSON,
  duration_ms INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_retrieval_run_user_time (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_tool_call (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  session_id VARCHAR(64) NOT NULL,
  message_id BIGINT,
  tool_name VARCHAR(100) NOT NULL,
  input_json JSON,
  output_text LONGTEXT,
  status VARCHAR(30) DEFAULT 'success',
  error_message TEXT,
  latency_ms INT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_tool_session_time (session_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sync_task (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT,
  source_type VARCHAR(30) NOT NULL,
  source_url VARCHAR(500),
  target_type VARCHAR(30),
  knowledge_base_id BIGINT,
  status VARCHAR(30) DEFAULT 'pending',
  result_message TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS document_task (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  document_id BIGINT NOT NULL,
  knowledge_base_id BIGINT NOT NULL,
  task_type VARCHAR(30) NOT NULL,
  status VARCHAR(30) DEFAULT 'pending',
  stage VARCHAR(30) DEFAULT 'uploading',
  progress INT DEFAULT 0,
  retry_count INT DEFAULT 0,
  error_message TEXT,
  started_at DATETIME DEFAULT NULL,
  finished_at DATETIME DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_document_task_doc (document_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_user (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  email VARCHAR(255) UNIQUE,
  username VARCHAR(80) UNIQUE,
  display_name VARCHAR(120),
  avatar_url VARCHAR(500),
  password_hash VARCHAR(255),
  auth_provider VARCHAR(30) DEFAULT 'local',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS oauth_account (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  provider VARCHAR(30) NOT NULL,
  provider_user_id VARCHAR(120) NOT NULL,
  email VARCHAR(255),
  username VARCHAR(120),
  avatar_url VARCHAR(500),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_provider_user (provider, provider_user_id),
  KEY idx_oauth_account_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS auth_session (
  id VARCHAR(128) PRIMARY KEY,
  user_id BIGINT NOT NULL,
  user_agent VARCHAR(500),
  expires_at DATETIME NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_auth_session_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
