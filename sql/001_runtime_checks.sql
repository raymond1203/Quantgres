SELECT version();

SELECT
    current_setting('server_version_num')::integer AS server_version_num,
    current_database() AS database_name,
    current_user AS user_name;

SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm')
ORDER BY extname;
