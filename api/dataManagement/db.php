<?php

$db_host = '';
$db_name = '';
$db_user = '';
$db_pass = '';
$db_source = 'none';

// ─── Method 1: Load from .env file ─────────────────────────────
$env_path = dirname(__DIR__) . '/.env';
if (file_exists($env_path)) {
    $env = [];
    $lines = file($env_path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if ($lines !== false) {
        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '' || $line[0] === '#') continue;
            if (strpos($line, '=') === false) continue;
            $parts = explode('=', $line, 2);
            $env[trim($parts[0])] = trim($parts[1]);
        }
    }

    $db_host = $env['DB_HOST'] ?? '';
    $db_name = $env['DB_NAME'] ?? '';
    $db_user = $env['DB_USER'] ?? '';
    $db_pass = $env['DB_PASS'] ?? '';

    if (!empty($db_host) && !empty($db_name) && !empty($db_user)) {
        $db_source = 'env';
    }
}

// ─── Method 2: Load from wp-config.php (traverse up) ───────────
if ($db_source === 'none') {
    $dir = __DIR__;
    $max_depth = 10; // safety limit
    $found = false;

    while ($max_depth-- > 0) {
        $wp_config_path = $dir . '/wp-config.php';
        if (file_exists($wp_config_path)) {
            $found = true;
            break;
        }
        $parent = realpath($dir . '/..');
        if ($parent === false || $parent === $dir) break; // reached root
        $dir = $parent;
    }

    if ($found) {
        // Extract DB constants from wp-config.php without executing it fully
        $wp_content = @file_get_contents($wp_config_path);
        if ($wp_content !== false) {
            // Parse define('CONSTANT', 'value') patterns
            $wp_defines = [];
            if (preg_match_all("/define\s*\(\s*['\"](\w+)['\"]\s*,\s*['\"]([^'\"]*?)['\"]\s*\)/", $wp_content, $matches, PREG_SET_ORDER)) {
                foreach ($matches as $match) {
                    $wp_defines[$match[1]] = $match[2];
                }
            }

            $db_host = $wp_defines['DB_HOST'] ?? '';
            $db_name = $wp_defines['DB_NAME'] ?? '';
            $db_user = $wp_defines['DB_USER'] ?? '';
            $db_pass = $wp_defines['DB_PASSWORD'] ?? '';

            if (!empty($db_host) && !empty($db_name) && !empty($db_user)) {
                $db_source = 'wp-config';
            }
        }
    }
}

// ─── Method 3: Hardcoded fallback ──────────────────────────────
if ($db_source === 'none') {
    $db_host = 'localhost';
    $db_name = 'wordpress_db';
    $db_user = 'root';
    $db_pass = '';
    $db_source = 'hardcoded';

    error_log("[DataMatcher DB] WARNING: Using hardcoded fallback credentials. Neither .env nor wp-config.php found.");
}

// ─── Validate credentials before connecting ────────────────────
if (empty($db_host) || empty($db_name) || empty($db_user)) {
    http_response_code(500);
    echo json_encode([
        'success' => false,
        'error' => 'Database credentials are incomplete (source: ' . $db_source . ')',
    ]);
    error_log("[DataMatcher DB] FATAL: Incomplete DB credentials from source: $db_source");
    exit;
}

// Table prefix - change per client (e.g., 'pw_', 'wp_yoc_')
$table_prefix = 'pw_';

// API Security Key - must match Python backend config
$api_key = 'CHANGE_THIS_SECRET_KEY';

// ─── Connect to database ───────────────────────────────────────
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
    echo json_encode([
        'success' => false,
        'error' => 'Database connection failed (source: ' . $db_source . ')',
    ]);
    error_log("[DataMatcher DB] Connection failed (source: $db_source): " . $e->getMessage());
    exit;
}
