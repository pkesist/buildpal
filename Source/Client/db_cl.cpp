#include "boost/asio.hpp"
#include "boost/utility/string_ref.hpp"
#include "boost/filesystem/convenience.hpp"
#include "boost/filesystem/path.hpp"

#include <cassert>
#include <deque>
#include <iostream>
#include <memory>
#include <string>
#include <sstream>

char const compiler[] = "msvc";
unsigned int compilerSize = sizeof(compiler) / sizeof(compiler[0]) - 1;

char const compilerExeFilename[] = "cl.exe";

typedef std::vector<boost::filesystem::path> PathList;

PathList const & getPath()
{
    static PathList result;
    static bool initialized = false;
    if ( !initialized )
    {
        DWORD const size = GetEnvironmentVariable( "PATH", NULL, 0 );
        assert( size > 0 );
        char * const pathBuffer( static_cast<char *>( alloca( size ) ) );
        GetEnvironmentVariable( "PATH", pathBuffer, size );
        std::size_t last( 0 );
        for ( std::size_t iter( 0 ); iter != size; ++iter )
        {
            if ( ( pathBuffer[ iter ] == ';' ) && ( iter != last + 1 ) )
            {
                result.push_back( boost::filesystem::path( pathBuffer + last, pathBuffer + iter ) );
                last = iter + 1;
            }
        }
        initialized = true;
    }
    return result;
}

bool findOnPath( PathList const & pathList, boost::filesystem::path const file, boost::filesystem::path & result )
{
    for ( PathList::const_iterator iter( pathList.begin() ); iter != pathList.end(); ++iter )
    {
        boost::filesystem::path tmpPath = (*iter) / file;
        if ( boost::filesystem::exists( tmpPath ) )
        {
            result = tmpPath;
            return true;
        }
    }
    return false;
}

std::unique_ptr<char []> getPipeData( HANDLE pipe, DWORD & size )
{
    DWORD available = 0;
    if ( !PeekNamedPipe( pipe, 0, 0, 0, &available, 0 ) )
        available = 0;

    std::unique_ptr<char []> buffer;
    buffer.reset( new char[ available + 1 ] );
    if ( available )
        ReadFile( pipe, buffer.get(), available, &size, NULL );
    buffer[ available ] = '\0';

    return buffer;
}

class MsgReceiver
{
public:
    explicit MsgReceiver( boost::asio::ip::tcp::socket & socket )
        :
        socket_( socket ),
        currentSize_( 0 )
    {
    }

    void getMessage()
    {
        if ( currentSize_ )
        {
            parts_.clear();
            buf_.consume( currentSize_ );
            currentSize_ = 0;
        }
        boost::system::error_code readError;
        char const * start;
        currentSize_ = boost::asio::read_until( socket_, buf_, std::string( "\0\1", 2 ), readError );
        if ( readError )
        {
            std::cerr << "FATAL: Read failure (" << readError.message() << ")\n";
            exit( 1 );
        }
        boost::asio::streambuf::const_buffers_type bufs = buf_.data();
        start = boost::asio::buffer_cast<char const *>( bufs );
        for ( std::size_t stride( 0 ); stride < currentSize_ - 1; )
        {
            std::size_t const partLen( strlen( start + stride ) );
            parts_.push_back( std::make_pair( start + stride, partLen ) );
            stride += partLen + 1;
        }
    }

    std::pair<char const *, std::size_t> getPart( std::size_t index )
    {
        if ( index >= parts_.size() )
            return std::make_pair<char const *, std::size_t>( 0, 0 );
        return parts_[ index ];
    }

    void getPart( std::size_t index, char const * * buff, std::size_t * size )
    {
        std::pair<char const *, std::size_t> const result( getPart( index ) );
        if ( buff ) *buff = result.first;
        if ( size ) *size = result.second;
    }

    std::size_t parts() const { return parts_.size(); }

private:
    boost::asio::ip::tcp::socket & socket_;
    boost::asio::streambuf buf_;
    std::vector<std::pair<char const *, std::size_t> > parts_;
    std::size_t currentSize_;
};

int main( int argc, char * argv[] )
{
    boost::filesystem::path compilerExecutable;
    if ( !findOnPath( getPath(), compilerExeFilename, compilerExecutable ) )
    {
        std::cerr << "Failed to locate executable 'cl.exe' on PATH.\n";
        return -1;
    }

    DWORD size = GetEnvironmentVariable("DB_MGR_PORT", NULL, 0 );
    if ( size == 0 )
    {
        if ( GetLastError() == ERROR_ENVVAR_NOT_FOUND )
            std::cerr << "You must define DB_MGR_PORT environment variable.\n";
        else
            std::cerr << "Failed to get DB_MGR_PORT environment variable.\n";
        return -1;
    }

    if ( size > 256 )
    {
        std::cerr << "Invalid DB_MGR_PORT environment variable value.\n";
        return -1;
    }

    char * buffer = static_cast<char *>( alloca( size ) );
    GetEnvironmentVariable( "DB_MGR_PORT", buffer, size );
    unsigned short port = atoi( buffer );

    boost::system::error_code addressError;
    boost::asio::ip::address localhost = boost::asio::ip::address::from_string( "127.0.0.1", addressError );
    if ( addressError )
    {
        std::cerr << "Could not resolve address: " << addressError.message() << '\n';
        return -1;
    }
    boost::asio::ip::tcp::endpoint endpoint;
    endpoint.address( localhost );
    endpoint.port( port );

    boost::asio::io_service ioService;
    boost::asio::ip::tcp::socket socket( ioService );
    boost::system::error_code connectError;
    socket.connect( endpoint, connectError );
    if ( connectError )
    {
        std::cerr << "Failed to connect to 'localhost:" << port << "'.\n";
        return -1;
    }

    std::vector<boost::asio::const_buffer> req;

    req.push_back( boost::asio::buffer( compiler, compilerSize + 1 ) );
    std::string const compilerExeStr( compilerExecutable.string() );
    req.push_back( boost::asio::buffer( compilerExeStr.c_str(), compilerExeStr.size() + 1 ) );

    DWORD includeSize = GetEnvironmentVariable( "INCLUDE", NULL, 0 );
    if ( includeSize == 0 )
        req.push_back( boost::asio::buffer( "\0", 1 ) );
    else
    {
        char * includeBuffer = static_cast<char *>( _alloca( includeSize ) );
        GetEnvironmentVariable( "INCLUDE", includeBuffer, includeSize );
        includeBuffer[ includeSize ] = '\0';
        req.push_back( boost::asio::buffer( includeBuffer, includeSize ) );
    }

    DWORD const currentPathSize( GetCurrentDirectory( 0, NULL ) );
    char * currentPathBuffer = static_cast<char *>( _alloca( currentPathSize ) );
    GetCurrentDirectory( currentPathSize, currentPathBuffer );
    req.push_back( boost::asio::buffer( currentPathBuffer, currentPathSize ) );

    for ( int arg( 1 ); arg < argc; ++arg )
    {
        req.push_back( boost::asio::buffer( argv[arg], strlen( argv[arg] ) + 1 ) );
    }
    req.push_back( boost::asio::buffer( "\1", 1 ) );
    boost::system::error_code writeError;
    boost::asio::write( socket, req, writeError );

    MsgReceiver receiver( socket );
    {
        receiver.getMessage();
        assert( receiver.parts() == 1 );
        std::pair<char const *, std::size_t> data( receiver.getPart( 0 ) );
        assert( data.second == 13 );
        assert( memcmp( data.first, "TASK_RECEIVED", data.second ) == 0 );
    }

    while ( true )
    {
        receiver.getMessage();

        assert( receiver.parts() >= 1 );

        char const * request;
        std::size_t requestSize;
        receiver.getPart( 0, &request, &requestSize );

        if ( ( requestSize == 16 ) && strncmp( request, "EXECUTE_AND_EXIT", 16 ) == 0 )
        {
            assert( receiver.parts() == 2 );
            char const * commandLine;
            std::size_t commandLineSize;
            receiver.getPart( 1, &commandLine, &commandLineSize );

            // Create a copy on the stack as required by CreateProcess.
            char * const buffer = static_cast<char *>( alloca( commandLineSize + 1 ) );
            std::memcpy( buffer, commandLine, commandLineSize );
            buffer[ commandLineSize ] = 0;

            STARTUPINFO startupInfo = { sizeof(startupInfo) };
            PROCESS_INFORMATION processInfo;

            BOOL const apiResult = CreateProcess(
                NULL,
                buffer,
                NULL,
                NULL,
                FALSE,
                CREATE_NEW_PROCESS_GROUP,
                NULL,
                NULL,
                &startupInfo,
                &processInfo
            );

            if ( apiResult )
            {
                ::WaitForSingleObject( processInfo.hProcess, INFINITE );
                int result;
                GetExitCodeProcess( processInfo.hProcess, reinterpret_cast<LPDWORD>( &result ) );
                CloseHandle( processInfo.hProcess );
                CloseHandle( processInfo.hThread );
                return result;
            }
            else
            {
                std::cerr << "ERROR: CreateProcess()\n";
                return -1;
            }
        }
        else if ( ( requestSize == 18 ) && strncmp( request, "EXECUTE_GET_OUTPUT", 18 ) == 0 )
        {
            assert( receiver.parts() == 2 );
            char const * commandLine;
            std::size_t commandLineSize;
            receiver.getPart( 1, &commandLine, &commandLineSize );

            // Create a copy on the stack as required by CreateProcess.
            char * const buffer = static_cast<char *>( alloca( commandLineSize + 1 ) );
            std::memcpy( buffer, commandLine, commandLineSize );
            buffer[ commandLineSize ] = 0;

            SECURITY_ATTRIBUTES saAttr;
            saAttr.nLength = sizeof(SECURITY_ATTRIBUTES);
            saAttr.bInheritHandle = TRUE;
            saAttr.lpSecurityDescriptor = NULL;

            HANDLE stdOutRead, stdOutWrite;
            CreatePipe( &stdOutRead, &stdOutWrite, &saAttr, 0 );
            SetHandleInformation( stdOutRead, HANDLE_FLAG_INHERIT, 0 );
            HANDLE stdErrRead, stdErrWrite;
            CreatePipe( &stdErrRead, &stdErrWrite, &saAttr, 0 );
            SetHandleInformation( stdErrRead, HANDLE_FLAG_INHERIT, 0 );

            STARTUPINFO startupInfo = { 0 };
            startupInfo.cb = sizeof(STARTUPINFO);
            startupInfo.hStdError = stdErrWrite;
            startupInfo.hStdOutput = stdOutWrite;
            startupInfo.dwFlags |= STARTF_USESTDHANDLES;
            startupInfo.dwFlags |= STARTF_USESHOWWINDOW;
            startupInfo.wShowWindow = SW_HIDE;

            PROCESS_INFORMATION processInfo;

            BOOL const apiResult = CreateProcess(
                NULL,
                buffer,
                NULL,
                NULL,
                TRUE,
                CREATE_NEW_PROCESS_GROUP,
                NULL,
                NULL,
                &startupInfo,
                &processInfo
            );

            std::vector<boost::asio::const_buffer> res;
            if ( apiResult )
            {
                ::WaitForSingleObject( processInfo.hProcess, INFINITE );
                {
                    int result;
                    GetExitCodeProcess( processInfo.hProcess, reinterpret_cast<LPDWORD>( &result ) );
                    char buffer[20];
                    _itoa( result, buffer, 10 );
                    res.push_back( boost::asio::buffer( buffer, strlen( buffer ) + 1 ) );
                }
                DWORD stdOutSize;
                std::unique_ptr<char []> stdOut( getPipeData( stdOutRead, stdOutSize ) );
                res.push_back( boost::asio::buffer( stdOut.get(), stdOutSize + 1 ) );
                DWORD stdErrSize;
                std::unique_ptr<char []> stdErr( getPipeData( stdErrRead, stdErrSize ) );
                res.push_back( boost::asio::buffer( stdErr.get(), stdErrSize + 1 ) );
                res.push_back( boost::asio::buffer( "\1", 1 ) );
                boost::system::error_code writeError;
                boost::asio::write( socket, res, writeError );
                if ( writeError )
                {
                    std::cerr << "FATAL: Write failure (" << writeError.message() << ")\n";
                    exit( 1 );
                }
                CloseHandle( processInfo.hProcess );
                CloseHandle( processInfo.hThread );
                CloseHandle( stdOutRead );
                CloseHandle( stdErrRead );
                CloseHandle( stdOutWrite );
                CloseHandle( stdErrWrite );
            }
            else
            {
                std::cerr << "ERROR: CreateProcess()\n";
                return -1;
            }
        }
        else if ( ( requestSize == 4 ) && strncmp( request, "EXIT", 4 ) == 0 )
        {
            assert( receiver.parts() == 2 );
            char const * exitCode;
            std::size_t exitCodeSize;
            receiver.getPart( 1, &exitCode, &exitCodeSize );

            char * buffer = static_cast<char *>( _alloca( exitCodeSize + 1 ) );
            std::memcpy( buffer, exitCode, exitCodeSize );
            buffer[ exitCodeSize ] = 0;
            return atoi( buffer );
        }
        else if ( ( requestSize == 9 ) && strncmp( request, "COMPLETED", 9 ) == 0 )
        {
            assert( receiver.parts() == 4 );
            char const * retcode;
            std::size_t retcodeSize;
            receiver.getPart( 1, &retcode, &retcodeSize );

            char * buffer = static_cast<char *>( _alloca( retcodeSize + 1 ) );
            std::memcpy( buffer, retcode, retcodeSize );
            buffer[ retcodeSize ] = 0;
            int const result = atoi( buffer );

            char const * stdOut;
            std::size_t stdOutSize;
            receiver.getPart( 2, &stdOut, &stdOutSize );

            char const * stdErr;
            std::size_t stdErrSize;
            receiver.getPart( 3, &stdErr, &stdErrSize );

            std::cout << std::string( stdOut, stdOutSize );
            if ( stdErrSize )
                std::cerr << std::string( stdErr, stdErrSize );
            return result;
        }
        else if ( ( requestSize == 6 ) && strncmp( request, "GETENV", 6 ) == 0 )
        {
            assert( receiver.parts() == 2 );
            char const * var;
            std::size_t varSize;
            receiver.getPart( 1, &var, &varSize );
            char * ztVar = static_cast<char *>( _alloca( varSize + 1 ) );
            std::memcpy( ztVar, var, varSize );
            ztVar[ varSize ] = 0;

            DWORD size = GetEnvironmentVariable( ztVar, NULL, 0 );

            if ( size > 1024 )
            {
                std::cerr << "Invalid environment variable value.\n";
                return -1;
            }

            char * buffer = static_cast<char *>( alloca( size ) );
            GetEnvironmentVariable( ztVar, buffer, size );

            std::vector<boost::asio::const_buffer> res;
            res.push_back( boost::asio::buffer( buffer, size + 1 ) );
            res.push_back( boost::asio::buffer( "\1", 1 ) );
            boost::system::error_code writeError;
            boost::asio::write( socket, res, writeError );
            if ( writeError )
            {
                std::cerr << "FATAL: Write failure (" << writeError.message() << ")\n";
                exit( 1 );
            }
        }
        else if ( ( requestSize == 12 ) && strncmp( request, "LOCATE_FILES", 12 ) == 0 )
        {
            assert( receiver.parts() > 1 );
            std::vector<std::string> files;
            std::vector<boost::asio::const_buffer> res;
            // First search relative to compiler dir, then path.
            PathList pathList;
            pathList.push_back( compilerExecutable.parent_path() );
            PathList const & path( getPath() );
            std::copy( path.begin(), path.end(), std::back_inserter( pathList ) );

            for ( std::size_t part = 1; part < receiver.parts(); ++part )
            {
                char const * file;
                std::size_t fileSize;
                receiver.getPart( part, &file, &fileSize );
                boost::filesystem::path result;
                findOnPath( pathList, boost::filesystem::path( file, file + fileSize ), result );
                files.push_back( result.string() );
                res.push_back( boost::asio::buffer( files.back().c_str(), files.back().size() + 1 ) );
            }
            res.push_back( boost::asio::buffer( "\1", 1 ) );
            boost::system::error_code writeError;
            boost::asio::write( socket, res, writeError );
            if ( writeError )
            {
                std::cerr << "FATAL: Write failure (" << writeError.message() << ")\n";
                exit( 1 );
            }
        }
        else
        {
            std::cout << "ERROR: GOT " << std::string( request, requestSize );
            return -1;
        }
    }

    return 0;
}