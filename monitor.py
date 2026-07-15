#!/usr/bin/env python3
from check_status import check_all, cleanup_status
from push_utils import push_notifications


def main():
    status, notifications = check_all()
    # 清理 status.json 中已删除对象的残留记录（前端删除只改 rooms.json，残留靠这里清）
    cleanup_status()
    if notifications:
        try:
            push_notifications(notifications)
        except Exception as e:
            print(f"推送通知失败（不影响状态更新）: {e}")


if __name__ == "__main__":
    main()
