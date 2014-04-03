import sys

if __name__ == '__main__':
    from buildpal_server.__main__ import main
    result = main(sys.argv[1:])
    if result:
        sys.exit(result)

