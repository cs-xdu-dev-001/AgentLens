SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  description TEXT,
  applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS model_config (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  name TEXT NOT NULL,
  provider TEXT NOT NULL,
  model_type TEXT NOT NULL,
  base_url TEXT NOT NULL,
  api_key_cipher TEXT,
  model_name TEXT NOT NULL,
  temperature REAL,
  top_p REAL,
  max_tokens INTEGER,
  is_default INTEGER DEFAULT 0,
  status TEXT DEFAULT 'untested',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS knowledge_base (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  name TEXT NOT NULL,
  description TEXT,
  embedding_model_config_id INTEGER NOT NULL,
  document_count INTEGER DEFAULT 0,
  chunk_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'active',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS document (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  knowledge_base_id INTEGER NOT NULL,
  filename TEXT NOT NULL,
  file_type TEXT,
  file_size INTEGER,
  file_md5 TEXT NOT NULL,
  storage_path TEXT,
  parse_status TEXT DEFAULT 'pending',
  chunk_count INTEGER DEFAULT 0,
  error_message TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (knowledge_base_id, file_md5)
);
CREATE TABLE IF NOT EXISTS document_chunk (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  knowledge_base_id INTEGER NOT NULL,
  document_id INTEGER NOT NULL,
  chunk_index INTEGER NOT NULL,
  chunk_text TEXT,
  vector_id TEXT NOT NULL,
  token_count INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chat_session (
  id TEXT PRIMARY KEY,
  user_id INTEGER,
  title TEXT,
  knowledge_base_id INTEGER,
  chat_model_config_id INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chat_message (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  trace_json TEXT,
  skill_id INTEGER,
  skill_slug TEXT,
  skill_version TEXT,
  skill_content_hash TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS message_reference (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL,
  document_id INTEGER NOT NULL,
  chunk_id INTEGER NOT NULL,
  score REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS retrieval_run (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  knowledge_base_id INTEGER NOT NULL,
  message_id INTEGER,
  query TEXT NOT NULL,
  top_k INTEGER DEFAULT 5,
  status TEXT DEFAULT 'success',
  hit_count INTEGER DEFAULT 0,
  max_score REAL DEFAULT 0,
  quality_level TEXT DEFAULT 'no_match',
  quality_json TEXT,
  duration_ms INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS agent_run (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  user_message_id INTEGER,
  assistant_message_id INTEGER,
  goal_summary TEXT NOT NULL,
  trigger_mode TEXT NOT NULL DEFAULT 'auto',
  status TEXT NOT NULL DEFAULT 'planning',
  current_step_id TEXT,
  trace_json TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS agent_run_step (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  kind TEXT NOT NULL,
  tool_name TEXT,
  input_summary TEXT,
  output_summary TEXT,
  error_code TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (run_id, position)
);
CREATE TABLE IF NOT EXISTS agent_tool_call (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  message_id INTEGER,
  tool_name TEXT NOT NULL,
  input_json TEXT,
  output_text TEXT,
  status TEXT DEFAULT 'success',
  error_message TEXT,
  latency_ms INTEGER,
  skill_id INTEGER,
  skill_slug TEXT,
  skill_version TEXT,
  skill_content_hash TEXT,
  run_id TEXT,
  run_step_id TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tool_config (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  tool_name TEXT NOT NULL,
  provider TEXT NOT NULL,
  api_key_cipher TEXT,
  enabled INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (user_id, tool_name)
);
CREATE TABLE IF NOT EXISTS sync_task (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  source_type TEXT NOT NULL,
  source_url TEXT,
  target_type TEXT,
  knowledge_base_id INTEGER,
  status TEXT DEFAULT 'pending',
  result_message TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS document_task (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  document_id INTEGER NOT NULL,
  knowledge_base_id INTEGER NOT NULL,
  task_type TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  stage TEXT DEFAULT 'uploading',
  progress INTEGER DEFAULT 0,
  retry_count INTEGER DEFAULT 0,
  error_message TEXT,
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS app_user (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE,
  username TEXT UNIQUE,
  display_name TEXT,
  avatar_url TEXT,
  password_hash TEXT,
  auth_provider TEXT DEFAULT 'local',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS oauth_account (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  provider_user_id TEXT NOT NULL,
  email TEXT,
  username TEXT,
  avatar_url TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (provider, provider_user_id)
);
CREATE TABLE IF NOT EXISTS auth_session (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  user_agent TEXT,
  expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mcp_server (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, slug TEXT NOT NULL, url TEXT NOT NULL, auth_type TEXT NOT NULL, enabled INTEGER DEFAULT 1, status TEXT DEFAULT 'unknown', credentials_cipher TEXT, tools_json TEXT, enabled_tools_json TEXT, last_error_code TEXT, last_connected_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, slug)
);
CREATE TABLE IF NOT EXISTS mcp_oauth_session (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, server_id INTEGER NOT NULL, state_hash TEXT NOT NULL UNIQUE, pkce_verifier_cipher TEXT NOT NULL, return_to TEXT, expires_at TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS skill_package (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_user_id INTEGER NOT NULL,
  slug TEXT NOT NULL,
  display_name TEXT NOT NULL,
  description TEXT,
  version TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_url TEXT,
  source_ref TEXT,
  source_subpath TEXT,
  content_hash TEXT NOT NULL,
  package_path TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (owner_user_id, slug, content_hash)
);
CREATE TABLE IF NOT EXISTS user_skill (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  skill_package_id INTEGER NOT NULL,
  skill_slug TEXT NOT NULL,
  enabled INTEGER DEFAULT 1,
  installed_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (user_id, skill_slug)
);
CREATE TABLE IF NOT EXISTS skill_import (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  source_kind TEXT NOT NULL,
  staged_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  preview_json TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_user ON mcp_oauth_session(user_id);
CREATE INDEX IF NOT EXISTS idx_mcp_oauth_expires ON mcp_oauth_session(expires_at);
CREATE INDEX IF NOT EXISTS idx_document_kb ON document(knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_chunk_kb_doc ON document_chunk(knowledge_base_id, document_id);
CREATE INDEX IF NOT EXISTS idx_message_session_time ON chat_message(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_retrieval_run_user_time ON retrieval_run(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_run_user_time ON agent_run(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_run_session_time ON agent_run(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_run_step_run_position ON agent_run_step(run_id, position);
CREATE INDEX IF NOT EXISTS idx_tool_session_time ON agent_tool_call(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_document_task_doc ON document_task(document_id, created_at);
CREATE INDEX IF NOT EXISTS idx_auth_session_user ON auth_session(user_id);
CREATE INDEX IF NOT EXISTS idx_oauth_account_user ON oauth_account(user_id)
"""

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INT PRIMARY KEY,
  description VARCHAR(500),
  applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
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
  trace_json LONGTEXT,
  skill_id BIGINT,
  skill_slug VARCHAR(255),
  skill_version VARCHAR(100),
  skill_content_hash VARCHAR(128),
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
CREATE TABLE IF NOT EXISTS agent_run (
  id VARCHAR(64) PRIMARY KEY,
  user_id BIGINT NOT NULL,
  session_id VARCHAR(64) NOT NULL,
  user_message_id BIGINT,
  assistant_message_id BIGINT,
  goal_summary TEXT NOT NULL,
  trigger_mode VARCHAR(30) NOT NULL DEFAULT 'auto',
  status VARCHAR(30) NOT NULL DEFAULT 'planning',
  current_step_id VARCHAR(64),
  trace_json LONGTEXT,
  version INT NOT NULL DEFAULT 1,
  started_at DATETIME,
  finished_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_agent_run_user_time (user_id, created_at),
  KEY idx_agent_run_session_time (session_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS agent_run_step (
  id VARCHAR(64) PRIMARY KEY,
  run_id VARCHAR(64) NOT NULL,
  position INT NOT NULL,
  title VARCHAR(120) NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'pending',
  kind VARCHAR(30) NOT NULL,
  tool_name VARCHAR(160),
  input_summary TEXT,
  output_summary TEXT,
  error_code VARCHAR(100),
  attempt_count INT NOT NULL DEFAULT 0,
  started_at DATETIME,
  finished_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_agent_run_step_position (run_id, position),
  KEY idx_agent_run_step_run_position (run_id, position)
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
  skill_id BIGINT,
  skill_slug VARCHAR(255),
  skill_version VARCHAR(100),
  skill_content_hash VARCHAR(128),
  run_id VARCHAR(64),
  run_step_id VARCHAR(64),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_tool_session_time (session_id, created_at),
  KEY idx_tool_run_step (run_id, run_step_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS tool_config (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  tool_name VARCHAR(100) NOT NULL,
  provider VARCHAR(50) NOT NULL,
  api_key_cipher TEXT,
  enabled TINYINT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tool_config_user_name (user_id, tool_name)
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
CREATE TABLE IF NOT EXISTS mcp_server (id BIGINT PRIMARY KEY AUTO_INCREMENT,user_id BIGINT NOT NULL,name VARCHAR(255) NOT NULL,slug VARCHAR(255) NOT NULL,url VARCHAR(500) NOT NULL,auth_type VARCHAR(30) NOT NULL,enabled TINYINT DEFAULT 1,status VARCHAR(30) DEFAULT 'unknown',credentials_cipher LONGTEXT,tools_json LONGTEXT,enabled_tools_json LONGTEXT,last_error_code VARCHAR(100),last_connected_at DATETIME,created_at DATETIME DEFAULT CURRENT_TIMESTAMP,updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,UNIQUE KEY uk_mcp_server_user_slug (user_id,slug)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS mcp_oauth_session (id VARCHAR(128) PRIMARY KEY,user_id BIGINT NOT NULL,server_id BIGINT NOT NULL,state_hash VARCHAR(255) NOT NULL UNIQUE,pkce_verifier_cipher LONGTEXT NOT NULL,return_to VARCHAR(500),expires_at DATETIME NOT NULL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP,KEY idx_mcp_oauth_user (user_id),KEY idx_mcp_oauth_expires (expires_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
;
CREATE TABLE IF NOT EXISTS skill_package (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  owner_user_id BIGINT NOT NULL,
  slug VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  description TEXT,
  version VARCHAR(100) NOT NULL,
  source_kind VARCHAR(30) NOT NULL,
  source_url VARCHAR(1000),
  source_ref VARCHAR(255),
  source_subpath VARCHAR(1000),
  content_hash VARCHAR(128) NOT NULL,
  package_path VARCHAR(1000) NOT NULL,
  manifest_json LONGTEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_skill_package_owner_slug_hash (owner_user_id, slug, content_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS user_skill (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  skill_package_id BIGINT NOT NULL,
  skill_slug VARCHAR(255) NOT NULL,
  enabled TINYINT DEFAULT 1,
  installed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_skill_user_slug (user_id, skill_slug)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS skill_import (
  id VARCHAR(128) PRIMARY KEY,
  user_id BIGINT NOT NULL,
  source_kind VARCHAR(30) NOT NULL,
  staged_path VARCHAR(1000) NOT NULL,
  content_hash VARCHAR(128) NOT NULL,
  preview_json LONGTEXT NOT NULL,
  expires_at DATETIME NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""
