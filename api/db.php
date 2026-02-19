<?php

// Database Configuration - Update these for each client
$db_host = 'localhost';
$db_name = 'DATABASE_NAME';
$db_user = 'DATABASE_USER';
$db_pass = 'DATABASE_PASS';

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
