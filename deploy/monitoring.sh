#!/bin/sh
# 외부 가동 확인: Route 53이 /api/health를 30초마다 본다 → 안 되면 CloudWatch 경보 → daiw-alerts(DAIW·소리허브와 같은 토픽) → 메일·Slack.
# /api/health를 배포한 뒤 한 번 실행한다. 다시 실행해도 같은 것을 쓴다 (caller-reference·경보 이름이 같으면 새로 만들지 않는다). 비용: 상태 확인 월 약 $1
set -e
AWS="aws --profile kcal-personal --region us-east-1" # Route 53 지표는 us-east-1에만 있다
TOPIC=arn:aws:sns:us-east-1:376981472569:daiw-alerts

# 깔린 앱이 쓰는 주소를 본다. caretable.kr도 같은 서버지만 도메인·인증서는 따로 보지 않는다
CHECK=$($AWS route53 create-health-check --caller-reference caretable-api-health \
  --health-check-config Type=HTTPS,FullyQualifiedDomainName=api.kcalai.link,Port=443,ResourcePath=/api/health,RequestInterval=30,FailureThreshold=3,EnableSNI=true \
  --query HealthCheck.Id --output text)
$AWS route53 change-tags-for-resource --resource-type healthcheck --resource-id "$CHECK" --add-tags Key=Name,Value=caretable-api
sleep 180 # 지표가 쌓이기 전에 경보를 만들면 빠진 지표를 실패로 보고 곧바로 오탐 메일이 나간다
$AWS cloudwatch put-metric-alarm --alarm-name caretable-api-down \
  --alarm-description 'api.kcalai.link/api/health 실패. 이유: journalctl -u kcalai -n 100, task-logs/error_log.txt' \
  --namespace AWS/Route53 --metric-name HealthCheckStatus --dimensions Name=HealthCheckId,Value="$CHECK" \
  --statistic Minimum --period 60 --evaluation-periods 2 --threshold 1 --comparison-operator LessThanThreshold \
  --treat-missing-data breaching --alarm-actions "$TOPIC" --ok-actions "$TOPIC"
echo "상태 확인 $CHECK, 경보 caretable-api-down → daiw-alerts"
