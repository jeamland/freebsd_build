#!/bin/sh

if [ x"$1" != x"-V" ]; then
    echo "This is a fake make that only does version queries. -V required."
    exit 1
fi

case "$2" in
    KERN_IDENT)
        echo "MINIMAL"
        ;;
    CC)
        echo "cc"
        ;;
    *)
        echo "Unknown variable: $2"
        exit 1
        ;;
esac
