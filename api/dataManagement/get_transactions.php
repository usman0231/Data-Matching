<?php
header('Content-Type: application/json');
require_once __DIR__ . '/db.php';

// Verify API key (case-insensitive header lookup)
$headers = array_change_key_case(getallheaders(), CASE_LOWER);
$provided_key = $headers['x-api-key'] ?? ($_GET['api_key'] ?? '');
if ($provided_key !== $api_key) {
    http_response_code(401);
    echo json_encode(['error' => 'Unauthorized']);
    exit;
}

$days = isset($_GET['days']) ? (int)$_GET['days'] : 2;
$days = min(max($days, 1), 30);

$page = isset($_GET['page']) ? (int)$_GET['page'] : 1;
$limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 5000;
$limit = min($limit, 10000);
$offset = ($page - 1) * $limit;

$table = $table_prefix . 'transactions';

// Get total count
$count_sql = "SELECT COUNT(*) as total FROM `$table`
              WHERE paya_reference IS NOT NULL
              AND paya_reference != ''
              AND date >= DATE_SUB(NOW(), INTERVAL :days DAY)";
$count_stmt = $pdo->prepare($count_sql);
$count_stmt->execute(['days' => $days]);
$total = (int)$count_stmt->fetch()['total'];

// Fetch transaction data
$sql = "SELECT
            id, DID, TID, order_id, paya_reference, charge_id,
            card_fee, charge_amount, totalamount, refund, reason,
            paymenttype, status, date
        FROM `$table`
        WHERE paya_reference IS NOT NULL
        AND paya_reference != ''
        AND date >= DATE_SUB(NOW(), INTERVAL :days DAY)
        ORDER BY id DESC
        LIMIT :limit OFFSET :offset";

$stmt = $pdo->prepare($sql);
$stmt->bindValue('days', $days, PDO::PARAM_INT);
$stmt->bindValue('limit', $limit, PDO::PARAM_INT);
$stmt->bindValue('offset', $offset, PDO::PARAM_INT);
$stmt->execute();
$rows = $stmt->fetchAll();

echo json_encode([
    'success' => true,
    'total' => $total,
    'page' => $page,
    'limit' => $limit,
    'has_more' => ($offset + $limit) < $total,
    'data' => $rows
], JSON_NUMERIC_CHECK);
