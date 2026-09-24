CREATE TABLE h3_cells (
	h3_index VARCHAR(16) NOT NULL, 
	resolution INTEGER NOT NULL, 
	area_ha FLOAT NOT NULL, 
	geom geometry(POLYGON,4326) NOT NULL, 
	centroid geometry(POINT,4326) NOT NULL, 
	elevation_m FLOAT, 
	slope_deg FLOAT, 
	water_distance_m FLOAT, 
	terrain_source VARCHAR(96), 
	water_source VARCHAR(96), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (h3_index)
);

CREATE TABLE model_versions (
	id UUID NOT NULL, 
	kind VARCHAR(64) NOT NULL, 
	version VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	coefficients JSONB NOT NULL, 
	metrics JSONB NOT NULL, 
	activated_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE pilots (
	slug VARCHAR(32) NOT NULL, 
	name VARCHAR(96) NOT NULL, 
	center geometry(POINT,4326) NOT NULL, 
	boundary geometry(POLYGON,4326) NOT NULL, 
	radius_km FLOAT NOT NULL, 
	timezone VARCHAR(64) NOT NULL, 
	observation_stations JSONB NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (slug), 
	UNIQUE (name)
);

CREATE TABLE satellite_scenes (
	id VARCHAR(180) NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	collection VARCHAR(64) NOT NULL, 
	acquired_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	cloud_cover_pct FLOAT, 
	processing_status VARCHAR(32) NOT NULL, 
	valid_fraction FLOAT, 
	assets JSONB NOT NULL, 
	properties JSONB NOT NULL, 
	footprint geometry(MULTIPOLYGON,4326), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE system_state (
	key VARCHAR(96) NOT NULL, 
	value JSONB NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE water_points (
	osm_id VARCHAR(64) NOT NULL, 
	name VARCHAR(180), 
	feature_type VARCHAR(64) NOT NULL, 
	geom geometry(POINT,4326) NOT NULL, 
	tags JSONB NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (osm_id)
);

CREATE TABLE calibration_imports (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	checksum VARCHAR(64) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	imported_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	row_count INTEGER NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	diagnostics JSONB NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug)
);

CREATE TABLE cell_observations (
	id UUID NOT NULL, 
	h3_index VARCHAR(16) NOT NULL, 
	scene_id VARCHAR(180) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ndvi FLOAT, 
	ndmi FLOAT, 
	valid_fraction FLOAT NOT NULL, 
	quality_flags JSONB NOT NULL, 
	model_version VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_cell_scene UNIQUE (h3_index, scene_id), 
	FOREIGN KEY(h3_index) REFERENCES h3_cells (h3_index) ON DELETE CASCADE, 
	FOREIGN KEY(scene_id) REFERENCES satellite_scenes (id) ON DELETE CASCADE
);

CREATE TABLE forecast_runs (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	model VARCHAR(96) NOT NULL, 
	requested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	generated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	valid_from TIMESTAMP WITH TIME ZONE NOT NULL, 
	valid_to TIMESTAMP WITH TIME ZONE NOT NULL, 
	checksum VARCHAR(64) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	units JSONB NOT NULL, 
	raw_payload JSONB NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug)
);

CREATE TABLE ingestion_runs (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	requested_from DATE, 
	requested_to DATE, 
	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	records_seen INTEGER NOT NULL, 
	records_written INTEGER NOT NULL, 
	latency_ms INTEGER, 
	discovered_fields JSONB NOT NULL, 
	diagnostics JSONB NOT NULL, 
	error_code VARCHAR(64), 
	error_message TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug)
);

CREATE TABLE raw_source_payloads (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	requested_from DATE, 
	requested_to DATE, 
	checksum VARCHAR(64) NOT NULL, 
	received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	UNIQUE (checksum)
);

CREATE TABLE user_profiles (
	auth_user_id UUID NOT NULL, 
	default_pilot_slug VARCHAR(32) NOT NULL, 
	email VARCHAR(320), 
	display_name VARCHAR(120) NOT NULL, 
	timezone VARCHAR(64) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	onboarding_completed BOOLEAN NOT NULL, 
	is_system_owner BOOLEAN NOT NULL, 
	notification_preferences JSONB NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (auth_user_id), 
	FOREIGN KEY(default_pilot_slug) REFERENCES pilots (slug)
);

CREATE TABLE alert_rules (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	owner_user_id UUID NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	metric VARCHAR(64), 
	comparator VARCHAR(8), 
	threshold FLOAT, 
	lookahead_hours INTEGER NOT NULL, 
	cooldown_minutes INTEGER NOT NULL, 
	channels JSONB NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	severity VARCHAR(16) NOT NULL, 
	response_mode VARCHAR(24) NOT NULL, 
	last_triggered_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	FOREIGN KEY(owner_user_id) REFERENCES user_profiles (auth_user_id) ON DELETE CASCADE
);

CREATE TABLE audit_events (
	id UUID NOT NULL, 
	actor_user_id UUID, 
	action VARCHAR(96) NOT NULL, 
	entity_type VARCHAR(64) NOT NULL, 
	entity_id VARCHAR(180), 
	details JSONB NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_user_id) REFERENCES user_profiles (auth_user_id) ON DELETE SET NULL
);

CREATE TABLE calibration_samples (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	external_sample_id VARCHAR(128) NOT NULL, 
	sampled_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	geom geometry(POINT,4326) NOT NULL, 
	dry_matter_kg_ha FLOAT NOT NULL, 
	method VARCHAR(180) NOT NULL, 
	quadrat_area_m2 FLOAT NOT NULL, 
	metadata JSONB NOT NULL, 
	import_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	UNIQUE (external_sample_id), 
	FOREIGN KEY(import_id) REFERENCES calibration_imports (id) ON DELETE SET NULL
);

CREATE TABLE data_source_settings (
	pilot_slug VARCHAR(32) NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	schedule VARCHAR(96), 
	mapping JSONB NOT NULL, 
	updated_by_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (pilot_slug, source), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	FOREIGN KEY(updated_by_id) REFERENCES user_profiles (auth_user_id) ON DELETE SET NULL
);

CREATE TABLE forecast_points (
	id UUID NOT NULL, 
	forecast_run_id UUID NOT NULL, 
	valid_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	temperature_c FLOAT, 
	relative_humidity_pct FLOAT, 
	precipitation_probability_pct FLOAT, 
	precipitation_mm FLOAT, 
	uv_index FLOAT, 
	wind_speed_m_s FLOAT, 
	wind_gust_m_s FLOAT, 
	et0_mm FLOAT, 
	quality_flags JSONB NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_forecast_run_valid_at UNIQUE (forecast_run_id, valid_at), 
	FOREIGN KEY(forecast_run_id) REFERENCES forecast_runs (id) ON DELETE CASCADE
);

CREATE TABLE route_runs (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	requested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	start_point geometry(POINT,4326) NOT NULL, 
	end_point geometry(POINT,4326) NOT NULL, 
	parameters JSONB NOT NULL, 
	total_distance_m FLOAT, 
	total_time_s FLOAT, 
	geojson JSONB, 
	elevation_profile JSONB NOT NULL, 
	diagnostics JSONB NOT NULL, 
	error_code VARCHAR(64), 
	owner_user_id UUID, 
	name VARCHAR(180), 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	FOREIGN KEY(owner_user_id) REFERENCES user_profiles (auth_user_id) ON DELETE SET NULL
);

CREATE TABLE telemetry_observations (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	station_id VARCHAR(96) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	metric VARCHAR(64) NOT NULL, 
	depth_cm FLOAT, 
	value FLOAT NOT NULL, 
	unit VARCHAR(32) NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	quality_flags JSONB NOT NULL, 
	model_version VARCHAR(64), 
	raw_payload_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_telemetry_identity UNIQUE NULLS NOT DISTINCT (station_id, observed_at, metric, depth_cm), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	FOREIGN KEY(raw_payload_id) REFERENCES raw_source_payloads (id) ON DELETE SET NULL
);

CREATE TABLE missions (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	owner_user_id UUID NOT NULL, 
	title VARCHAR(180) NOT NULL, 
	description TEXT NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	scheduled_start TIMESTAMP WITH TIME ZONE, 
	scheduled_end TIMESTAMP WITH TIME ZONE, 
	route_run_id UUID, 
	herd_tlu FLOAT, 
	notes TEXT NOT NULL, 
	revision INTEGER NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	FOREIGN KEY(owner_user_id) REFERENCES user_profiles (auth_user_id) ON DELETE CASCADE, 
	FOREIGN KEY(route_run_id) REFERENCES route_runs (id) ON DELETE SET NULL
);

CREATE TABLE report_runs (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	owner_user_id UUID NOT NULL, 
	mission_id UUID NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	parameters JSONB NOT NULL, 
	evidence_manifest JSONB NOT NULL, 
	pdf_object_key VARCHAR(512), 
	json_object_key VARCHAR(512), 
	error_message TEXT, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	FOREIGN KEY(owner_user_id) REFERENCES user_profiles (auth_user_id) ON DELETE CASCADE, 
	FOREIGN KEY(mission_id) REFERENCES missions (id) ON DELETE CASCADE
);

CREATE TABLE response_cases (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	owner_user_id UUID NOT NULL, 
	rule_id UUID, 
	mission_id UUID NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	severity VARCHAR(16) NOT NULL, 
	revision INTEGER NOT NULL, 
	resolution_notes TEXT, 
	dismissal_reason TEXT, 
	acknowledged_at TIMESTAMP WITH TIME ZONE, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	dismissed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	FOREIGN KEY(owner_user_id) REFERENCES user_profiles (auth_user_id) ON DELETE CASCADE, 
	FOREIGN KEY(rule_id) REFERENCES alert_rules (id) ON DELETE SET NULL, 
	FOREIGN KEY(mission_id) REFERENCES missions (id) ON DELETE CASCADE
);

CREATE TABLE sample_submissions (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	owner_user_id UUID NOT NULL, 
	sample_code VARCHAR(40) NOT NULL, 
	external_reference VARCHAR(128), 
	sampled_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	geom geometry(POINT,4326) NOT NULL, 
	dry_matter_kg_ha FLOAT NOT NULL, 
	method VARCHAR(180) NOT NULL, 
	quadrat_area_m2 FLOAT NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	review_notes TEXT, 
	submitted_at TIMESTAMP WITH TIME ZONE, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	reviewed_by_id UUID, 
	calibration_sample_id UUID, 
	mission_id UUID, 
	revision INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_sample_owner_reference UNIQUE (owner_user_id, external_reference), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	FOREIGN KEY(owner_user_id) REFERENCES user_profiles (auth_user_id) ON DELETE CASCADE, 
	FOREIGN KEY(reviewed_by_id) REFERENCES user_profiles (auth_user_id) ON DELETE SET NULL, 
	FOREIGN KEY(calibration_sample_id) REFERENCES calibration_samples (id) ON DELETE SET NULL, 
	FOREIGN KEY(mission_id) REFERENCES missions (id) ON DELETE SET NULL
);

CREATE TABLE alerts (
	id UUID NOT NULL, 
	pilot_slug VARCHAR(32) NOT NULL, 
	owner_user_id UUID NOT NULL, 
	rule_id UUID, 
	response_case_id UUID, 
	kind VARCHAR(32) NOT NULL, 
	title VARCHAR(180) NOT NULL, 
	message TEXT NOT NULL, 
	severity VARCHAR(16) NOT NULL, 
	payload JSONB NOT NULL, 
	dedupe_key VARCHAR(180) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	acknowledged_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pilot_slug) REFERENCES pilots (slug), 
	FOREIGN KEY(owner_user_id) REFERENCES user_profiles (auth_user_id) ON DELETE CASCADE, 
	FOREIGN KEY(rule_id) REFERENCES alert_rules (id) ON DELETE SET NULL, 
	FOREIGN KEY(response_case_id) REFERENCES response_cases (id) ON DELETE SET NULL, 
	UNIQUE (dedupe_key)
);

CREATE TABLE response_updates (
	id UUID NOT NULL, 
	response_case_id UUID NOT NULL, 
	author_user_id UUID NOT NULL, 
	notes TEXT NOT NULL, 
	geom geometry(POINT,4326) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(response_case_id) REFERENCES response_cases (id) ON DELETE CASCADE, 
	FOREIGN KEY(author_user_id) REFERENCES user_profiles (auth_user_id) ON DELETE CASCADE
);

CREATE TABLE sample_attachments (
	id UUID NOT NULL, 
	submission_id UUID NOT NULL, 
	object_key VARCHAR(512) NOT NULL, 
	original_filename VARCHAR(255) NOT NULL, 
	content_type VARCHAR(64) NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	checksum VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(submission_id) REFERENCES sample_submissions (id) ON DELETE CASCADE, 
	UNIQUE (object_key)
);

CREATE TABLE notification_deliveries (
	id UUID NOT NULL, 
	alert_id UUID NOT NULL, 
	channel VARCHAR(24) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	provider_id VARCHAR(180), 
	attempts INTEGER NOT NULL, 
	last_error TEXT, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	next_attempt_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(alert_id) REFERENCES alerts (id) ON DELETE CASCADE
);

CREATE TABLE response_attachments (
	id UUID NOT NULL, 
	update_id UUID NOT NULL, 
	object_key VARCHAR(512) NOT NULL, 
	original_filename VARCHAR(255) NOT NULL, 
	content_type VARCHAR(64) NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	checksum VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(update_id) REFERENCES response_updates (id) ON DELETE CASCADE, 
	UNIQUE (object_key)
);