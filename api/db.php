<?php

// Load credentials from .env file
$env_path = dirname(__DIR__) . '/.env';
if (!file_exists($env_path)) {
    http_response_code(500);
    echo json_encode(['error' => '.env file not found']);
    exit;
}

$env = [];
foreach (file($env_path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    if (str_starts_with(trim($line), '#')) continue;
    if (strpos($line, '=') === false) continue;
    [$key, $val] = explode('=', $line, 2);
    $env[trim($key)] = trim($val);
}

$db_host = $env['DB_HOST'] ?? 'localhost';
$db_name = $env['DB_NAME'] ?? '';
$db_user = $env['DB_USER'] ?? '';
$db_pass = $env['DB_PASS'] ?? '';

// Table prefix - change per client (e.g., 'pw_', 'wp_yoc_')
$table_prefix = 'pw_';

// API Security Key - must match Python backend config
$api_key = 'CHANGE_THIS_SECRET_KEY';

try {
    $pdo = new PDO(
        "mysql:host=$db_host;dbname=$db_name;charset=utf8mb4",
        $db_user,
        $db_pass,
        [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ]
    );
} catch (PDOException $e) {
    http_response_code(500);
    echo json_encode(['error' => 'Database connection failed']);
    exit;
}
