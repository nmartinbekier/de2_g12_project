PULSAR_ADMIN_PATH=$(cat pulsar_admin_path.txt)/bin/pulsar-admin
PULSAR_ADMIN_PATH="${PULSAR_ADMIN_PATH/#\~/$HOME}"

HERE=$(dirname "$0")
AGGREGATE_FUNCTIONS_PATH=$(realpath ../$HERE/aggregate_functions.py)

echo Initializing functions using file $AGGREGATE_FUNCTIONS_PATH

$PULSAR_ADMIN_PATH functions create \
  --py $AGGREGATE_FUNCTIONS_PATH \
  --classname aggregate_functions.AggregateFunction \
  --tenant public \
  --namespace static \
  --name aggregate_functions \
  --inputs persistent://public/default/basic_repo_info,persistent://public/default/repo_with_tests,persistent://public/static/repo_with_ci,persistent://public/static/aggregate_languages_info