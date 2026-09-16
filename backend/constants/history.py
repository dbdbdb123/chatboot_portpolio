"""대화 세션 저장소의 키와 보관 정책."""

from datetime import timedelta


# 메시지는 세션의 마지막 활동 시간이 아니라 각 메시지의 생성 시각을 기준으로 보관한다.
# 따라서 오래된 메시지가 제거되어도 같은 세션의 최근 메시지는 그대로 유지된다.
CHAT_MESSAGE_RETENTION = timedelta(days=3)

# Redis 키가 다른 애플리케이션 데이터와 충돌하지 않도록 공통 네임스페이스를 사용한다.
CHAT_HISTORY_KEY_PREFIX = "mori:chat"
