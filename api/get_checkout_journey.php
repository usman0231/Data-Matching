<?php
header('Content-Type: application/json');
require_once __DIR__ . '/db.php';

// Verify API key
$headers = getallheaders();
$provided_key = $headers['X-Api-Key'] ?? ($_GET['api_key'] ?? '');
if ($provided_key !== $api_key) {
    http_response_code(401);
    echo json_encode(['error' => 'Unauthorized']);
    exit;
}

$days = isset($_GET['days']) ? (int)$_GET['days'] : 2;
$days = min(max($days, 1), 30); // clamp 1-30

$page = isset($_GET['page']) ? (int)$_GET['page'] : 1;
$limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 5000;
$limit = min($limit, 10000);
$offset = ($page - 1) * $limit;

$table = $table_prefix . 'checkout_journey';

// Get total count first
$count_sql = "SELECT COUNT(*) as total FROM `$table`
              WHERE stripe_payment_intent_id IS NOT NULL
              AND stripe_payment_intent_id != ''
              AND created_at >= DATE_SUB(NOW(), INTERVAL :days DAY)";
$count_stmt = $pdo->prepare($count_sql);
$count_stmt->execute(['days' => $days]);
$total = (int)$count_stmt->fetch()['total'];

// Fetch data with pagination
$sql = "SELECT
            id, invoiceid, order_no, stripe_payment_intent_id,
            payment_status, total_amount, currency, donor_email,
            donor_name, donor_phone, cart_item_count, subtotal,
            processing_fee, reached_thankyou, created_at
        FROM `$table`
        WHERE stripe_payment_intent_id IS NOT NULL
        AND stripe_payment_intent_id != ''
        AND payment_status LIKE 'payment_confirmed'
        AND created_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
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
