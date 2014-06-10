import sys

if __name__ == '__main__':
    from buildpal.__main__ import main
    main([sys.argv[0], 'client', '--run', 'cmd.exe', '/Q', '/K', 'echo BuildPal Console'])

