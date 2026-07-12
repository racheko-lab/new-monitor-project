#!/bin/bash

set -e

case "${1:-once}" in
    once)
        python monitor.py
        ;;
    loop)
        while true; do
            python monitor.py
            sleep 60
        done
        ;;
    posts)
        python check_posts.py
        ;;
    all)
        python monitor.py
        python check_posts.py
        ;;
    *)
        echo "Usage: $0 [once|loop|posts|all]"
        exit 1
        ;;
esac
