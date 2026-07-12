#!/usr/bin/env python3
from check_status import check_all
from push_utils import push_notifications


def main():
    status, notifications = check_all()
    if notifications:
        push_notifications(notifications)


if __name__ == "__main__":
    main()
