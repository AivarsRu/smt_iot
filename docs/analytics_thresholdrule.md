classDiagram
direction BT
class analytics_thresholdrule {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(128) code
   varchar(256) name
   text description
   boolean is_enabled
   double precision lower_bound
   double precision upper_bound
   varchar(16) severity
   text message_template
   boolean close_when_normal
   integer sort_order
   uuid asset_id
   uuid device_id
   uuid metric_id
   uuid sensor_id
   uuid site_id
   uuid id
}
class assets_asset {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(64) code
   varchar(256) name
   varchar(32) asset_type
   varchar(32) status
   text description
   double precision latitude
   double precision longitude
   varchar(128) external_id
   uuid parent_id
   uuid site_id
   uuid id
}
class assets_device {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(128) device_uid
   varchar(256) name
   varchar(64) device_type
   boolean is_simulated
   integer expected_interval_seconds
   varchar(64) firmware_version
   varchar(32) status
   timestamp with time zone last_seen_at
   uuid asset_id
   uuid site_id
   uuid id
}
class assets_sensor {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(64) code
   varchar(256) name
   varchar(64) sensor_type
   text description
   uuid device_id
   uuid id
}
class assets_site {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(64) code
   varchar(256) name
   text description
   text address
   double precision latitude
   double precision longitude
   varchar(64) timezone
   boolean is_demo
   uuid id
}
class auth_group {
   varchar(150) name
   integer id
}
class auth_group_permissions {
   integer group_id
   integer permission_id
   bigint id
}
class auth_permission {
   varchar(255) name
   integer content_type_id
   varchar(100) codename
   integer id
}
class auth_user {
   varchar(128) password
   timestamp with time zone last_login
   boolean is_superuser
   varchar(150) username
   varchar(150) first_name
   varchar(150) last_name
   varchar(254) email
   boolean is_staff
   boolean is_active
   timestamp with time zone date_joined
   integer id
}
class auth_user_groups {
   integer user_id
   integer group_id
   bigint id
}
class auth_user_user_permissions {
   integer user_id
   integer permission_id
   bigint id
}
class digital_twin_assetstate {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(32) status
   timestamp with time zone last_seen_at
   timestamp with time zone last_measurement_at
   double precision last_temperature_c
   double precision last_voltage_v
   double precision last_current_a
   double precision last_power_w
   double precision last_battery_soc_pct
   integer active_anomaly_count
   boolean has_active_anomaly
   jsonb state_payload
   uuid asset_id
   uuid device_id
   uuid last_raw_message_id
   uuid site_id
   uuid id
}
class django_admin_log {
   timestamp with time zone action_time
   text object_id
   varchar(200) object_repr
   smallint action_flag
   text change_message
   integer content_type_id
   integer user_id
   integer id
}
class django_content_type {
   varchar(100) app_label
   varchar(100) model
   integer id
}
class django_migrations {
   varchar(255) app
   varchar(255) name
   timestamp with time zone applied
   bigint id
}
class django_session {
   text session_data
   timestamp with time zone expire_date
   varchar(40) session_key
}
class events_event {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(32) event_type
   varchar(16) severity
   varchar(16) status
   varchar(256) title
   text description
   timestamp with time zone detected_at
   timestamp with time zone acknowledged_at
   timestamp with time zone closed_at
   varchar(64) source
   jsonb payload
   uuid asset_id
   uuid device_id
   uuid measurement_id
   uuid metric_id
   uuid raw_message_id
   uuid sensor_id
   uuid site_id
   uuid id
}
class iot_config_deviceprofile {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(64) code
   varchar(128) name
   varchar(64) device_type
   text description
   integer default_expected_interval_seconds
   uuid id
}
class iot_config_deviceprofilemetric {
   boolean is_required
   integer sort_order
   uuid profile_id
   uuid metric_id
   bigint id
}
class iot_config_metricdefinition {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(64) key
   varchar(128) display_name
   text description
   varchar(32) unit
   varchar(16) data_type
   double precision normal_min
   double precision normal_max
   double precision warning_min
   double precision warning_max
   boolean is_required
   integer sort_order
   uuid id
}
class iot_config_mqtttopictemplate {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(128) name
   varchar(16) topic_type
   varchar(512) template
   text description
   uuid id
}
class simulator_simulatormetricprofile {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   double precision base_value
   double precision min_value
   double precision max_value
   double precision noise_amplitude
   varchar(32) generation_mode
   boolean is_enabled
   integer sort_order
   uuid metric_id
   uuid scenario_device_id
   uuid id
}
class simulator_simulatorrun {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   timestamp with time zone started_at
   timestamp with time zone finished_at
   varchar(32) status
   integer messages_published
   text error_message
   uuid scenario_id
   uuid id
}
class simulator_simulatorscenario {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(64) code
   varchar(256) name
   text description
   varchar(32) default_status
   integer interval_seconds
   timestamp with time zone last_run_at
   uuid site_id
   uuid id
}
class simulator_simulatorscenariodevice {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   boolean is_enabled
   integer sort_order
   varchar(32) status_override
   uuid device_id
   uuid device_profile_id
   uuid scenario_id
   uuid id
}
class telemetry_measurement {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   timestamp with time zone timestamp
   double precision value_float
   integer value_int
   boolean value_bool
   varchar(512) value_text
   varchar(32) unit
   varchar(16) quality
   boolean is_anomalous
   uuid asset_id
   uuid device_id
   uuid metric_id
   uuid sensor_id
   uuid site_id
   uuid raw_message_id
   uuid id
}
class telemetry_rawmessage {
   timestamp with time zone created_at
   timestamp with time zone updated_at
   boolean is_active
   jsonb metadata
   varchar(16) source_type
   varchar(512) topic
   jsonb payload
   text payload_text
   varchar(128) message_id
   varchar(128) device_uid
   timestamp with time zone received_at
   timestamp with time zone payload_timestamp
   varchar(16) processing_status
   text error_message
   varchar(32) parser_version
   uuid asset_id
   uuid device_id
   uuid site_id
   uuid id
}

analytics_thresholdrule  -->  assets_asset : asset_id:id
analytics_thresholdrule  -->  assets_device : device_id:id
analytics_thresholdrule  -->  assets_sensor : sensor_id:id
analytics_thresholdrule  -->  assets_site : site_id:id
analytics_thresholdrule  -->  iot_config_metricdefinition : metric_id:id
assets_asset  -->  assets_asset : parent_id:id
assets_asset  -->  assets_site : site_id:id
assets_device  -->  assets_asset : asset_id:id
assets_device  -->  assets_site : site_id:id
assets_sensor  -->  assets_device : device_id:id
auth_group_permissions  -->  auth_group : group_id:id
auth_group_permissions  -->  auth_permission : permission_id:id
auth_permission  -->  django_content_type : content_type_id:id
auth_user_groups  -->  auth_group : group_id:id
auth_user_groups  -->  auth_user : user_id:id
auth_user_user_permissions  -->  auth_permission : permission_id:id
auth_user_user_permissions  -->  auth_user : user_id:id
digital_twin_assetstate  -->  assets_asset : asset_id:id
digital_twin_assetstate  -->  assets_device : device_id:id
digital_twin_assetstate  -->  assets_site : site_id:id
digital_twin_assetstate  -->  telemetry_rawmessage : last_raw_message_id:id
django_admin_log  -->  auth_user : user_id:id
django_admin_log  -->  django_content_type : content_type_id:id
events_event  -->  assets_asset : asset_id:id
events_event  -->  assets_device : device_id:id
events_event  -->  assets_sensor : sensor_id:id
events_event  -->  assets_site : site_id:id
events_event  -->  iot_config_metricdefinition : metric_id:id
events_event  -->  telemetry_measurement : measurement_id:id
events_event  -->  telemetry_rawmessage : raw_message_id:id
iot_config_deviceprofilemetric  -->  iot_config_deviceprofile : profile_id:id
iot_config_deviceprofilemetric  -->  iot_config_metricdefinition : metric_id:id
simulator_simulatormetricprofile  -->  iot_config_metricdefinition : metric_id:id
simulator_simulatormetricprofile  -->  simulator_simulatorscenariodevice : scenario_device_id:id
simulator_simulatorrun  -->  simulator_simulatorscenario : scenario_id:id
simulator_simulatorscenario  -->  assets_site : site_id:id
simulator_simulatorscenariodevice  -->  assets_device : device_id:id
simulator_simulatorscenariodevice  -->  iot_config_deviceprofile : device_profile_id:id
simulator_simulatorscenariodevice  -->  simulator_simulatorscenario : scenario_id:id
telemetry_measurement  -->  assets_asset : asset_id:id
telemetry_measurement  -->  assets_device : device_id:id
telemetry_measurement  -->  assets_sensor : sensor_id:id
telemetry_measurement  -->  assets_site : site_id:id
telemetry_measurement  -->  iot_config_metricdefinition : metric_id:id
telemetry_measurement  -->  telemetry_rawmessage : raw_message_id:id
telemetry_rawmessage  -->  assets_asset : asset_id:id
telemetry_rawmessage  -->  assets_device : device_id:id
telemetry_rawmessage  -->  assets_site : site_id:id
