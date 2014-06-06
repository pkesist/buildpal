import sys

if __name__ == '__main__':
    from buildpal.__main__ import main
    result = main(sys.argv)
    if result:
        sys.exit(result)
