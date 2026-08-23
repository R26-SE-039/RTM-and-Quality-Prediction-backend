-- Raw SQL equivalent of the SQLAlchemy models in app/models.py.
-- Not required for normal use (the app auto-creates tables on startup via
-- SQLAlchemy metadata), but provided for manual inspection / non-Python setup.

CREATE TYPE test_status AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE coverage_status AS ENUM ('FULLY COVERED', 'PARTIAL', 'NOT COVERED');
CREATE TYPE risk_level AS ENUM ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW');
CREATE TYPE action_type AS ENUM ('redundant', 'critical', 'weak');
CREATE TYPE activity_type AS ENUM ('test_created', 'quality_analyzed', 'gap_detected', 'model_loaded');

CREATE TABLE requirements (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    source VARCHAR(255) DEFAULT '',
    req_type VARCHAR(100) DEFAULT '',
    wbs_deliverables VARCHAR(255) DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE acceptance_criteria (
    id SERIAL PRIMARY KEY,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE test_cases (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    steps TEXT DEFAULT '',
    acceptance_criteria_id INTEGER NOT NULL REFERENCES acceptance_criteria(id) ON DELETE CASCADE,
    assertion_strength FLOAT DEFAULT 0.0,
    coverage_percent FLOAT DEFAULT 0.0,
    boundary_coverage FLOAT DEFAULT 0.0,
    error_handling FLOAT DEFAULT 0.0,
    mutation_resistance FLOAT DEFAULT 0.0,
    quality_score FLOAT,
    status test_status DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE code_coverage (
    id SERIAL PRIMARY KEY,
    test_case_id INTEGER NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    module_name VARCHAR(255) NOT NULL,
    coverage_percent FLOAT DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE rtm_entries (
    id SERIAL PRIMARY KEY,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    acceptance_criteria_id INTEGER REFERENCES acceptance_criteria(id) ON DELETE CASCADE,
    test_case_id INTEGER REFERENCES test_cases(id) ON DELETE CASCADE,
    coverage_percent FLOAT DEFAULT 0.0,
    status coverage_status NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE coverage_gaps (
    id SERIAL PRIMARY KEY,
    requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    risk_level risk_level NOT NULL,
    recommendation TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE portfolio_actions (
    id SERIAL PRIMARY KEY,
    test_case_id INTEGER NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    action_type action_type NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE activity_logs (
    id SERIAL PRIMARY KEY,
    activity_type activity_type NOT NULL,
    title VARCHAR(255) NOT NULL,
    detail VARCHAR(255) DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE project_settings (
    id SERIAL PRIMARY KEY,
    project_name VARCHAR(255) DEFAULT '',
    project_manager VARCHAR(255) DEFAULT '',
    project_description TEXT DEFAULT '',
    component2_project_id VARCHAR(64),
    component1_iteration_id VARCHAR(64),
    updated_at TIMESTAMPTZ DEFAULT now()
);
