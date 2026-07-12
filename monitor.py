#!/usr/bin/env python3
from check_status import check_all
from push_utils import push_notifications


def main():
    status, notifications = check_all()
    if notifications:
        try:
            push_notifications(notifications)
        except Exception as e:
            print(f"推送通知失败（不影响状态更新）: {e}")


if __name__ == "__main__":
    main()
