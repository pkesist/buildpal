#include <boost/asio.hpp>
#include <boost/filesystem/convenience.hpp>
#include <boost/filesystem/path.hpp>
#include <boost/spirit/include/qi.hpp>
#include <boost/spirit/include/karma.hpp>
#include <boost/system/error_code.hpp>
#include <boost/timer/timer.hpp>

#include <llvm/Support/CommandLine.h>

#include <cassert>
#include <iostream>
#include <memory>
#include <list>
#include <set>
#include <string>
#include <sstream>
#include <windows.h>

char const compiler[] = "msvc";
unsigned int compilerSize = sizeof(compiler) / sizeof(compiler[0]) - 1;
char const defaultPortName[] = "default";
unsigned int defaultPortNameSize = sizeof(defaultPortName) / sizeof(defaultPortName[0]);

char const compilerExeFilename[] = "cl.exe";
std::size_t compilerExeFilenameSize = sizeof(compilerExeFilename) / sizeof(compilerExeFilename[0]) - 1;

typedef std::vector<boost::filesystem::path> PathList;

namespace
{
  class StringSaver : public llvm::cl::StringSaver
  {
  public:
      virtual const char * SaveString( char const * str )
      {
          return storage_.insert( str ).first->c_str();
      }
  private:
      std::set<std::string> storage_;
  };
}

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

    std::unique_ptr<char []> buffer( new char[ available + 1 ] );
    if ( available )
        ReadFile( pipe, buffer.get(), available, &size, NULL );
    else
        size = 0;
    buffer[ available ] = '\0';
    return buffer;
}

class MsgSender
{
public:
    MsgSender() { initMessage(); }

    void addPart( char const * ptr, std::size_t size )
    {
        std::array<unsigned char, 4> const ar = {(size >> 24) & 0xFF, (size >> 16) & 0xFF, (size >> 8) & 0xFF, size & 0xFF};
        lengths_.push_back( ar );
        buffers_.push_back( boost::asio::buffer( &lengths_.back()[0], sizeof( lengths_.back() ) ) );
        if ( size != 0 )
            buffers_.push_back( boost::asio::buffer( ptr, size ) );
        totalLength_ += 4 + size;
        partCount_ += 1;
    }

    template <class Stream>
    void send( Stream & sock, boost::system::error_code & error )
    {
        lengthBuffer_[0] = (totalLength_ >> 24) & 0xFF;
        lengthBuffer_[1] = (totalLength_ >> 16) & 0xFF;
        lengthBuffer_[2] = (totalLength_ >>  8) & 0xFF;
        lengthBuffer_[3] = (totalLength_      ) & 0xFF;
        lengthBuffer_[4] = (partCount_ >> 8 ) & 0xFF;
        lengthBuffer_[5] = (partCount_      ) & 0xFF;
        boost::asio::write( sock, buffers_, error );
        initMessage();
    }

private:
    void initMessage()
    {
        buffers_.clear();
        lengths_.clear();
        partCount_ = 0;
        buffers_.push_back( boost::asio::buffer( &lengthBuffer_[0], sizeof( lengthBuffer_ ) ) );
        totalLength_ = sizeof(lengthBuffer_) - 4;
    }

private:
    std::size_t totalLength_;
    std::size_t partCount_;
    std::array<unsigned char, 6> lengthBuffer_;
    std::list<std::array<unsigned char, 4> > lengths_;
    std::vector<boost::asio::const_buffer> buffers_;
};


class MsgReceiver
{
public:
    template <class Stream>
    void getMessage( Stream & sock, boost::system::error_code & error )
    {
        parts_.clear();

        std::array<unsigned char, 6> lengthBuffer;
        boost::system::error_code readError;
        boost::asio::read( sock, boost::asio::buffer( &lengthBuffer[0], sizeof( lengthBuffer ) ), error );
        if ( error )
            return;
        std::size_t const totalSize =
            (lengthBuffer[0] << 24) |
            (lengthBuffer[1] << 16) |
            (lengthBuffer[2] << 8 ) |
            (lengthBuffer[3]      );

        std::size_t const partCount =
            (lengthBuffer[4] << 8) |
            (lengthBuffer[5]     );

        buf_.resize( totalSize - 2 );
        boost::asio::read( sock, boost::asio::buffer( &buf_[0], totalSize - 2 ), error );
        if ( error )
            return;

        char const * const start = buf_.data();
        unsigned char const * const ustart = reinterpret_cast<unsigned char const *>( start );
        std::size_t offset( 0 );
        std::size_t partsFound = 0;
        while ( offset < totalSize - 2 )
        {
            std::size_t const partLen = 
                (ustart[offset + 0] << 24) |
                (ustart[offset + 1] << 16) |
                (ustart[offset + 2] << 8 ) |
                (ustart[offset + 3]      );
            offset += 4;
            parts_.push_back( llvm::StringRef( start + offset, partLen ) );
            offset += partLen;
            ++partsFound;
        }
        if ( ( offset != totalSize - 2 ) || ( partsFound != partCount ) )
        {
            error = boost::system::errc::make_error_code( boost::system::errc::protocol_error );
            return;
        }
    }

    llvm::StringRef getPart( std::size_t index )
    {
        if ( index >= parts_.size() )
            return llvm::StringRef();
        return parts_[ index ];
    }

    std::size_t parts() const { return parts_.size(); }

private:
    std::vector<char> buf_;
    std::vector<llvm::StringRef> parts_;
};

template <typename Parser, typename Attribute>
bool parse( char const * buffer, Parser const & parser, Attribute & val )
{
    char const * end = buffer + strlen( buffer );
    return boost::spirit::qi::parse( buffer, end, parser, val ) && ( buffer == end );
}

template <typename Generator, typename Attribute>
bool generate( char * & buffer, Generator const & generator, Attribute const & attr )
{
    return boost::spirit::karma::generate( buffer, generator, attr );
}

int createProcess( char * commandLine )
{
    STARTUPINFO startupInfo = { sizeof(startupInfo) };
    PROCESS_INFORMATION processInfo;

    BOOL const apiResult = CreateProcess(
        NULL,
        commandLine,
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

int runLocally()
{
    std::cout << "Running command locally...\n";
    char const * commandLine = GetCommandLine();
    std::size_t len = strlen( commandLine );
    char const * argsPos = commandLine;

    bool inQuote = false;
    bool foundNonSpace = false;
    bool escape = false;

    for ( ; ; ++argsPos )
    {
        bool const isSpace = *argsPos == ' ' || *argsPos == '\t' || *argsPos == '\0';
        if ( *argsPos == '\\' )
        {
            escape = !escape;
        }

        else if ( isSpace )
        {
            if ( foundNonSpace && !inQuote )
                break;
            escape = false;
        }

        else if ( *argsPos == '"' && !escape )
        {
            inQuote = !inQuote;
        }
        else
        {
            foundNonSpace = true;
            escape = false;
        }
    }

    std::size_t const argsLen = len - ( argsPos - commandLine );
    std::size_t const commandLineSize = sizeof(compilerExeFilename) - 1 + argsLen;

    // Create a copy on the stack as required by CreateProcess.
    std::size_t pos( 0 );
    char * const buffer = static_cast<char *>( alloca( commandLineSize + 1 ) );
    std::memcpy( buffer, compilerExeFilename, sizeof(compilerExeFilename) - 1 );
    pos += sizeof(compilerExeFilename) - 1;
    std::memcpy( buffer + pos, argsPos, argsLen );
    buffer[ commandLineSize ] = 0;

    return createProcess( buffer );
}

class Fallback
{
public:
    explicit Fallback( bool fallbackDisabled )
        : fallbackDisabled_( fallbackDisabled ) {}

    int complete() const
    {
        return fallbackDisabled_ ? -1 : runLocally();
    }
private:
    bool fallbackDisabled_;
};


int main( int argc, char * argv[] )
{
    boost::timer::auto_cpu_timer t( std::cout, "Command took %w seconds.\n" );
    boost::filesystem::path compilerExecutable;
    if ( !findOnPath( getPath(), compilerExeFilename, compilerExecutable ) )
    {
        std::cerr << "Failed to locate executable 'cl.exe' on PATH.\n";
        return -1;
    }

    bool disableFallback = false;
    {
        DWORD size = GetEnvironmentVariable( "BP_DISABLE_FALLBACK", NULL, 0 );
        disableFallback = ( size != 0 ) || ( GetLastError() != ERROR_ENVVAR_NOT_FOUND );
    }
    Fallback const fallback( disableFallback );

    DWORD size = GetEnvironmentVariable("BP_MGR_PORT", NULL, 0 );
    char const * portName;
    if ( size == 0 )
    {
        portName = defaultPortName;
        size = defaultPortNameSize;
    }
    else if ( size > 256 )
    {
        std::cerr << "Invalid BP_MGR_PORT environment variable value (value too big).\n";
        return fallback.complete();
    }
    else
    {
        char * tmp = static_cast<char *>( alloca( size ) );
        GetEnvironmentVariable( "BP_MGR_PORT", tmp, size );
        portName = tmp;
    }

#ifdef BOOST_WINDOWS
    HANDLE pipe;
    char const pipeStreamPrefix[] = "\\\\.\\pipe\\BuildPal_";
    std::size_t const pipeStreamPrefixSize = sizeof(pipeStreamPrefix) / sizeof(pipeStreamPrefix[0]) - 1;

    char * pipeName = static_cast<char *>( alloca( pipeStreamPrefixSize + size ) );
    std::memcpy( pipeName, pipeStreamPrefix, pipeStreamPrefixSize );
    std::memcpy( pipeName + pipeStreamPrefixSize, portName, size );

    for ( ; ;  )
    {
        pipe = ::CreateFile(
            pipeName,                                     // LPCTSTR lpFileName,
            GENERIC_READ | GENERIC_WRITE,                 // DWORD dwDesiredAccess,
            0,                                            // DWORD dwShareMode,
            NULL,                                         // LPSECURITY_ATTRIBUTES lpSecurityAttributes,
            OPEN_EXISTING,                                // DWORD dwCreationDisposition,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED, // DWORD dwFlagsAndAttributes,
            NULL                                          // HANDLE hTemplateFile
        );

        if ( pipe != INVALID_HANDLE_VALUE )
            break;

        if ( GetLastError() == ERROR_PIPE_BUSY )
        {
            WaitNamedPipe( pipeName, NMPWAIT_USE_DEFAULT_WAIT );
            continue;
        }
            
        boost::system::error_code const error( ::GetLastError(), boost::system::system_category() );
        std::cerr << "Failed to create pipe '" << pipeName << "'. (" << error.message() << ").\n";
        return fallback.complete();
    }
    typedef boost::asio::windows::stream_handle StreamType;

    boost::asio::io_service ioService;
    StreamType sock( ioService, pipe );
#else
    unsigned short port;
    if ( !parse( portName, boost::spirit::qi::ushort_, port ) )
    {
        std::cerr << "Failed to parse BP_MGR_PORT environment variable value.\n";
        return fallback.complete();
    }
    
    boost::asio::ip::address localhost;
    boost::system::error_code addressError;
    localhost = boost::asio::ip::address::from_string( "127.0.0.1", addressError );
    if ( addressError )
    {
        std::cerr << "Could not resolve address: " << addressError.message() << '\n';
        return fallback.complete();
    }
    
    boost::asio::io_service ioService;
    typedef boost::asio::ip::tcp::socket StreamType;
    boost::asio::ip::tcp::socket sock( ioService );
    boost::asio::ip::tcp::endpoint endpoint;
    endpoint.address( localhost );
    endpoint.port( port );
    
    boost::system::error_code connectError;
    sock.connect( endpoint, connectError );
    if ( connectError )
    {
        std::cerr << "Failed to connect to 'localhost:" << port << "'.\n";
        return fallback.complete();
    }
#endif

    MsgSender msgSender;

    msgSender.addPart( compiler, compilerSize );
    std::string const compilerExeStr( compilerExecutable.string() );
    msgSender.addPart( compilerExeStr.c_str(), compilerExeStr.size() );

    DWORD includeSize = GetEnvironmentVariable( "INCLUDE", NULL, 0 );
    if ( includeSize == 0 )
        msgSender.addPart( "", 0 );
    else
    {
        char * includeBuffer = static_cast<char *>( _alloca( includeSize ) );
        GetEnvironmentVariable( "INCLUDE", includeBuffer, includeSize );
        includeBuffer[ includeSize ] = '\0';
        msgSender.addPart( includeBuffer, includeSize - 1 );
    }

    DWORD const currentPathSize( GetCurrentDirectory( 0, NULL ) );
    char * currentPathBuffer = static_cast<char *>( _alloca( currentPathSize ) );
    GetCurrentDirectory( currentPathSize, currentPathBuffer );
    msgSender.addPart( currentPathBuffer, currentPathSize - 1 );

    llvm::SmallVector<char const *, 16> newArgv;
    for ( int i( 1 ); i < argc; ++i )
        newArgv.push_back( argv[ i ] );

    StringSaver saver;
    if ( !llvm::cl::ExpandResponseFiles( saver, llvm::cl::TokenizeGNUCommandLine, newArgv ) )
    {
        // Still not fixed in Clang 3.4.
        //std::cerr << "FATAL: Failed to expand response files.";
        //return fallback.complete();
    }

    for ( unsigned int arg( 0 ); arg < newArgv.size(); ++arg )
    {
        msgSender.addPart( newArgv[ arg ], strlen( newArgv[arg] ) );
    }

    boost::system::error_code writeError;
    msgSender.send( sock, writeError );
    if ( writeError )
    {
        std::cerr << "Failed to send message (" << writeError.message() << ").\n";
        return fallback.complete();
    }

    MsgReceiver receiver;
    while ( true )
    {
        boost::system::error_code error;
        receiver.getMessage( sock, error );
        if ( error )
        {
            std::cerr << "ERROR: Failed to get message (" << error.message() << ")\n";
            return fallback.complete();
        }

        if ( receiver.parts() == 0 )
        {
            std::cerr << "ERROR: Empty message\n";
            return fallback.complete();
        }

        llvm::StringRef const request = receiver.getPart( 0 );

        if ( request == "RUN_LOCALLY" )
        {
            if ( receiver.parts() != 1 )
            {
                std::cerr << "ERROR: Invalid message length\n";
                return fallback.complete();
            }
            return runLocally();
        }
        else if ( request == "EXECUTE_AND_EXIT" )
        {
            if ( receiver.parts() != 2 )
            {
                std::cerr << "ERROR: Invalid message length\n";
                return fallback.complete();
            }
            llvm::StringRef const commandLine = receiver.getPart( 1 );
            // Running the compiler is implied.
            std::size_t const compilerExecutableSize( compilerExecutable.string().size() );

            char * const buffer = static_cast<char *>( alloca( compilerExecutableSize + 1 + commandLine.size() + 1 ) );
            std::memcpy( buffer, compilerExecutable.string().c_str(), compilerExecutableSize );
            buffer[ compilerExecutableSize ] = ' ';
            std::memcpy( buffer + compilerExecutableSize + 1, commandLine.data(), commandLine.size() );
            buffer[ compilerExecutableSize + 1 + commandLine.size() ] = 0;

            return createProcess( buffer );
        }
        else if ( request == "EXECUTE_GET_OUTPUT" )
        {
            if ( receiver.parts() != 2 )
            {
                std::cerr << "ERROR: Invalid message length\n";
                return fallback.complete();
            }

            llvm::StringRef const commandLine = receiver.getPart( 1 );
            // Running the compiler is implied.
            std::size_t const compilerExecutableSize( compilerExecutable.string().size() );

            char * const buffer = static_cast<char *>( alloca( compilerExecutableSize + 1 + commandLine.size() + 1 ) );
            std::memcpy( buffer, compilerExecutable.string().c_str(), compilerExecutableSize );
            buffer[ compilerExecutableSize ] = ' ';
            std::memcpy( buffer + compilerExecutableSize + 1, commandLine.data(), commandLine.size() );
            buffer[ compilerExecutableSize + 1 + commandLine.size() ] = 0;

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

            if ( apiResult )
            {
                char retcodeBuffer[ 16 ];
                ::WaitForSingleObject( processInfo.hProcess, INFINITE );
                {
                    int result;
                    GetExitCodeProcess( processInfo.hProcess, reinterpret_cast<LPDWORD>( &result ) );
                    char * buf = retcodeBuffer;
                    bool const genResult = generate( buf, boost::spirit::karma::int_, result );
                    assert( genResult );
                    assert( retcodeBuffer < buf );
                    assert( buf - retcodeBuffer <= sizeof(retcodeBuffer) );
                    assert( buf - retcodeBuffer > 0 );
                    msgSender.addPart( retcodeBuffer, buf - retcodeBuffer );
                }
                DWORD stdOutSize;
                std::unique_ptr<char []> stdOut( getPipeData( stdOutRead, stdOutSize ) );
                std::cout << std::string( stdOut.get(), stdOutSize ) << '\n';
                msgSender.addPart( stdOut.get(), stdOutSize );
                DWORD stdErrSize;
                std::unique_ptr<char []> stdErr( getPipeData( stdErrRead, stdErrSize ) );
                msgSender.addPart( stdErr.get(), stdErrSize );
                std::cout << std::string( stdErr.get(), stdErrSize ) << '\n';
                boost::system::error_code writeError;
                msgSender.send( sock, writeError );
                if ( writeError )
                {
                    std::cerr << "Failed to send message (" << writeError.message() << ").\n";
                    return fallback.complete();
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
                return fallback.complete();
            }
        }
        else if ( request == "EXIT" )
        {
            if ( receiver.parts() != 4 )
            {
                std::cerr << "ERROR: Invalid message length\n";
                return fallback.complete();
            }
            llvm::StringRef retcode = receiver.getPart( 1 );

            char * buffer = static_cast<char *>( _alloca( retcode.size() + 1 ) );
            std::memcpy( buffer, retcode.data(), retcode.size() );
            buffer[ retcode.size() ] = 0;
            int result;
            if ( !parse( buffer, boost::spirit::int_, result ) )
            {
                std::cerr << "ERROR: Failed to parse exit code.\n" << buffer;
                return fallback.complete();
            }

            llvm::StringRef const stdOut = receiver.getPart( 2 );
            llvm::StringRef const stdErr = receiver.getPart( 3 );
            std::cout << stdOut.str();
            if ( stdErr.size() )
                std::cerr << stdErr.str();
            return result;
        }
        else if ( request == "LOCATE_FILES" )
        {
            if ( receiver.parts() <= 1 )
            {
                std::cerr << "ERROR: Invalid message length\n";
                return fallback.complete();
            }
            std::vector<std::string> files;
            // First search relative to compiler dir, then path.
            PathList pathList;
            pathList.push_back( compilerExecutable.parent_path() );
            PathList const & path( getPath() );
            std::copy( path.begin(), path.end(), std::back_inserter( pathList ) );

            for ( std::size_t part = 1; part < receiver.parts(); ++part )
            {
                llvm::StringRef file = receiver.getPart( part );
                boost::filesystem::path result;
                findOnPath( pathList, boost::filesystem::path( file.data(), file.data() + file.size() ), result );
                files.push_back( result.string() );
                msgSender.addPart( files.back().c_str(), files.back().size() );
            }
            boost::system::error_code writeError;
            msgSender.send( sock, writeError );
            if ( writeError )
            {
                std::cerr << "Failed to send message (" << writeError.message() << ").\n";
                return fallback.complete();
            }
        }
        else
        {
            std::cerr << "ERROR: GOT " << request.str();
            return fallback.complete();
        }
    }

    return 0;
}