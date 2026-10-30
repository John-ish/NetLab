create table if not exists hosts (
	host_id int generated always as identity primary key,
	hostname varchar(100) NOT NULL UNIQUE,
	ip_address varchar(45) NOT NULL UNIQUE,
	description varchar(120) NOT NULL DEFAULT '',
	ram_gb int CHECK (ram_gb > 0),
	status varchar(20) DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE', 'OFFLINE')),
	latency_ms int CHECK (latency_ms >= 0),
	last_seen timestamptz,
	check_interval int CHECK (check_interval > 0)
);

alter table hosts add column if not exists description varchar(120) NOT NULL DEFAULT '';
alter table hosts add column if not exists latency_ms int CHECK (latency_ms >= 0);
alter table hosts add column if not exists last_seen timestamptz;
alter table hosts add column if not exists check_interval int CHECK (check_interval > 0);
alter table hosts add column if not exists ssh_user varchar(64);
alter table hosts add column if not exists ssh_port int CHECK (ssh_port BETWEEN 1 AND 65535);
alter table hosts add column if not exists os_family varchar(10) CHECK (os_family = 'linux');

create table if not exists services (
	service_id int generated always as identity primary key,
	host_id int NOT NULL REFERENCES hosts(host_id) ON DELETE CASCADE,
	service_name varchar(100) NOT NULL,
	port_number INT CHECK (port_number BETWEEN 1 AND 65535),
	protocol varchar(10) NOT NULL DEFAULT 'TCP' CHECK (protocol IN ('TCP', 'UDP', 'HTTP', 'HTTPS')),
	check_interval int NOT NULL DEFAULT 5 CHECK (check_interval > 0),
	description varchar(120) NOT NULL DEFAULT '',
	status varchar(20) DEFAULT 'PENDING' CHECK (status IN ('RUNNING', 'WARNING', 'STOPPED', 'PENDING')),
	latency_ms real CHECK (latency_ms >= 0),
	last_check timestamptz,
	checks_total int NOT NULL DEFAULT 0,
	checks_passed int NOT NULL DEFAULT 0,
	status_since timestamptz
);

alter table services add column if not exists protocol varchar(10) NOT NULL DEFAULT 'TCP' CHECK (protocol IN ('TCP', 'UDP', 'HTTP', 'HTTPS'));
alter table services add column if not exists check_interval int NOT NULL DEFAULT 5 CHECK (check_interval > 0);
alter table services add column if not exists description varchar(120) NOT NULL DEFAULT '';
alter table services add column if not exists latency_ms real CHECK (latency_ms >= 0);
alter table services add column if not exists last_check timestamptz;
alter table services add column if not exists checks_total int NOT NULL DEFAULT 0;
alter table services add column if not exists checks_passed int NOT NULL DEFAULT 0;
alter table services add column if not exists status_since timestamptz;
alter table services add column if not exists cred_user varchar(100);
alter table services add column if not exists cred_password text;
alter table services add column if not exists cred_visible boolean NOT NULL DEFAULT false;
alter table services alter column host_id set not null;
alter table services drop constraint if exists services_status_check;
alter table services add constraint services_status_check CHECK (status IN ('RUNNING', 'WARNING', 'STOPPED', 'PENDING'));

create unique index if not exists services_host_name_port_key on services (host_id, service_name, port_number);

create table if not exists maintenance_logs (
	log_id int generated always as identity primary key,
	host_id int references hosts(host_id) on delete cascade,
	host_name varchar(100) NOT NULL,
	log_type varchar(10) NOT NULL DEFAULT 'USER' CHECK (log_type IN ('HOST', 'SERVICE', 'USER')),
	level varchar(10) NOT NULL DEFAULT 'INFO' CHECK (level IN ('INFO', 'WARNING', 'ERROR')),
	service_name varchar(100),
	changes_performed TEXT NOT NULL,
	log_date timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

alter table maintenance_logs add column if not exists host_name varchar(100);
update maintenance_logs m set host_name = h.hostname from hosts h where m.host_id = h.host_id and m.host_name is null;
alter table maintenance_logs alter column host_name set not null;
alter table maintenance_logs alter column host_id drop not null;
alter table maintenance_logs add column if not exists log_type varchar(10) NOT NULL DEFAULT 'USER' CHECK (log_type IN ('HOST', 'SERVICE', 'USER'));
alter table maintenance_logs add column if not exists level varchar(10) NOT NULL DEFAULT 'INFO' CHECK (level IN ('INFO', 'WARNING', 'ERROR'));
alter table maintenance_logs add column if not exists service_name varchar(100);
alter table maintenance_logs alter column log_date type timestamptz;
alter table maintenance_logs alter column log_date set not null;

create index if not exists maintenance_logs_date_idx on maintenance_logs (log_date desc, log_id desc);
create index if not exists maintenance_logs_host_idx on maintenance_logs (host_name);
