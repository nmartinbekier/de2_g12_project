PULSAR_ADMIN_PATH=$(cat pulsar_admin_path.txt)/bin/pulsar-admin
PULSAR_ADMIN_PATH="${PULSAR_ADMIN_PATH/#\~/$HOME}"

$PULSAR_ADMIN_PATH namespaces set-retention public/default --size 0 --time 0
$PULSAR_ADMIN_PATH namespaces set-deduplication public/default --enable
$PULSAR_ADMIN_PATH namespaces create public/static
$PULSAR_ADMIN_PATH namespaces set-retention public/static --size -1 --time -1
$PULSAR_ADMIN_PATH namespaces set-deduplication public/static --enable