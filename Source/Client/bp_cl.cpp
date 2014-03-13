#include "boost/asio.hpp"
#include "boost/filesystem/convenience.hpp"
#include "boost/filesystem/path.hpp"
#include "boost/spirit/include/qi.hpp"
#include "boost/spirit/include/karma.hpp"
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

char const compilerExeFilename[] = "cl.exe";

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

    std::unique_ptr<char []> buffer;
    buffer.reset( new char[ available + 1 ] );
    if ( available )
        ReadFile( pipe, buffer.get(), available, &size, NULL );
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
    void send( Stream & sock )
    {
        lengthBuffer_[0] = (totalLength_ >> 24) & 0xFF;
        lengthBuffer_[1] = (totalLength_ >> 16) & 0xFF;
        lengthBuffer_[2] = (totalLength_ >>  8) & 0xFF;
        lengthBuffer_[3] = (totalLength_      ) & 0xFF;
        lengthBuffer_[4] = (partCount_ >> 8 ) & 0xFF;
        lengthBuffer_[5] = (partCount_      ) & 0xFF;
        boost::system::error_code writeError;
        boost::asio::write( sock, buffers_, writeError );
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
    void getMessage( Stream & sock )
    {
        parts_.clear();

        std::array<unsigned char, 6> lengthBuffer;
        boost::system::error_code readError;
        boost::asio::read( sock, boost::asio::buffer( &lengthBuffer[0], sizeof( lengthBuffer ) ), readError );
        if ( readError )
        {
            std::cerr << "FATAL: Read failure (" << readError.message() << ")\n";
            exit( 1 );
        }
        std::size_t const totalSize =
            (lengthBuffer[0] << 24) |
            (lengthBuffer[1] << 16) |
            (lengthBuffer[2] << 8 ) |
            (lengthBuffer[3]      );

        std::size_t const partCount =
            (lengthBuffer[4] << 8) |
            (lengthBuffer[5]     );

        buf_.resize( totalSize - 2 );
        boost::asio::read( sock, boost::asio::buffer( &buf_[0], totalSize - 2 ), readError );
        if ( readError )
        {
            std::cerr << "FATAL: Read failure (" << readError.message() << ")\n";
            exit( 1 );
        }

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
            parts_.push_back( std::make_pair( start + offset, partLen ) );
            offset += partLen;
            ++partsFound;
        }
        if ( ( offset != totalSize - 2 ) || ( partsFound != partCount ) )
        {
            std::cerr << "FATAL: Invalid message\n";
            std::cerr << "    offset " << offset << ", should be " << totalSize - 2 << "\n";
            std::cerr << "    parts " << partsFound << ", should be " << partCount << "\n";
            exit( 1 );
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
    std::vector<char> buf_;
    std::vector<std::pair<char const *, std::size_t> > parts_;
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


int main( int argc, char * argv[] )
{
    boost::timer::auto_cpu_timer t( std::cout, "Command took %w seconds.\n" );
    boost::filesystem::path compilerExecutable;
    if ( !findOnPath( getPath(), compilerExeFilename, compilerExecutable ) )
    {
        std::cerr << "Failed to locate executable 'cl.exe' on PATH.\n";
        return -1;
    }

    DWORD size = GetEnvironmentVariable("BP_MGR_PORT", NULL, 0 );
    if ( size == 0 )
    {
        if ( GetLastError() == ERROR_ENVVAR_NOT_FOUND )
            std::cerr << "You must define BP_MGR_PORT environment variable.\n";
        else
            std::cerr << "Failed to get BP_MGR_PORT environment variable.\n";
        return runLocally();
    }

    if ( size > 256 )
    {
        std::cerr << "Invalid BP_MGR_PORT environment variable value (value too big).\n";
        return runLocally();
    }

#ifdef BOOST_WINDOWS
    HANDLE pipe;
    char const pipeStreamPrefix[] = "\\\\.\\pipe\\BuildPal_";
    std::size_t const pipeStreamPrefixSize = sizeof(pipeStreamPrefix) / sizeof(pipeStreamPrefix[0]) - 1;

    char * pipeName = static_cast<char *>( alloca( pipeStreamPrefixSize + size ) );
    std::memcpy( pipeName, pipeStreamPrefix, pipeStreamPrefixSize );
    GetEnvironmentVariable( "BP_MGR_PORT", pipeName + pipeStreamPrefixSize, size );

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
        return runLocally();
    }
    typedef boost::asio::windows::stream_handle StreamType;

    boost::asio::io_service ioService;
    StreamType sock( ioService, pipe );
#else
    unsigned short port;
    char * buffer = static_cast<char *>( alloca( size ) );
    GetEnvironmentVariable( "BP_MGR_PORT", buffer, size );
    
    if ( !parse( buffer, boost::spirit::qi::ushort_, port ) )
    {
        std::cerr << "Failed to parse BP_MGR_PORT environment variable value.\n";
        return runLocally();
    }
    
    boost::asio::ip::address localhost;
    boost::system::error_code addressError;
    localhost = boost::asio::ip::address::from_string( "127.0.0.1", addressError );
    if ( addressError )
    {
        std::cerr << "Could not resolve address: " << addressError.message() << '\n';
        return runLocally();
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
        return runLocally();
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
        //return -1;
    }

    for ( unsigned int arg( 0 ); arg < newArgv.size(); ++arg )
    {
        msgSender.addPart( newArgv[ arg ], strlen( newArgv[arg] ) );
    }

    msgSender.send( sock );

    MsgReceiver receiver;
    while ( true )
    {
        receiver.getMessage( sock );

        assert( receiver.parts() >= 1 );

        char const * request;
        std::size_t requestSize;
        receiver.getPart( 0, &request, &requestSize );

        if ( ( requestSize == 11 ) && strncmp( request, "RUN_LOCALLY", 11 ) == 0 )
        {
            assert( receiver.parts() == 1 );
            return runLocally();
        }
        else if ( ( requestSize == 16 ) && strncmp( request, "EXECUTE_AND_EXIT", 16 ) == 0 )
        {
            assert( receiver.parts() == 2 );
            char const * commandLine;
            std::size_t commandLineSize;
            receiver.getPart( 1, &commandLine, &commandLineSize );
            // Running the compiler is implied.
            std::size_t const compilerExecutableSize( compilerExecutable.string().size() );

            char * const buffer = static_cast<char *>( alloca( compilerExecutableSize + 1 + commandLineSize + 1 ) );
            std::memcpy( buffer, compilerExecutable.string().c_str(), compilerExecutableSize );
            buffer[ compilerExecutableSize ] = ' ';
            std::memcpy( buffer + compilerExecutableSize + 1, commandLine, commandLineSize );
            buffer[ compilerExecutableSize + 1 + commandLineSize ] = 0;

            return createProcess( buffer );
        }
        else if ( ( requestSize == 18 ) && strncmp( request, "EXECUTE_GET_OUTPUT", 18 ) == 0 )
        {
            assert( receiver.parts() == 2 );
            char const * commandLine;
            std::size_t commandLineSize;
            receiver.getPart( 1, &commandLine, &commandLineSize );

            // Running the compiler is implied.
            std::size_t const compilerExecutableSize( compilerExecutable.string().size() );

            char * const buffer = static_cast<char *>( alloca( compilerExecutableSize + 1 + commandLineSize + 1 ) );
            std::memcpy( buffer, compilerExecutable.string().c_str(), compilerExecutableSize + 1 );
            buffer[ compilerExecutableSize ] = ' ';
            std::memcpy( buffer + compilerExecutableSize + 1, commandLine, commandLineSize );
            buffer[ compilerExecutableSize + 1 + commandLineSize ] = 0;

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
                ::WaitForSingleObject( processInfo.hProcess, INFINITE );
                {
                    int result;
                    GetExitCodeProcess( processInfo.hProcess, reinterpret_cast<LPDWORD>( &result ) );
                    char * buffer = static_cast<char *>( _alloca( 16 ) );
                    char * buf = buffer;
                    bool const genResult = generate( buf, boost::spirit::karma::int_, result );
                    assert( genResult );
                    assert( buffer < buf );
                    assert( buf - buffer <= 16 );
                    msgSender.addPart( buffer, buf - buffer );
                }
                DWORD stdOutSize;
                std::unique_ptr<char []> stdOut( getPipeData( stdOutRead, stdOutSize ) );
                msgSender.addPart( stdOut.get(), stdOutSize );
                DWORD stdErrSize;
                std::unique_ptr<char []> stdErr( getPipeData( stdErrRead, stdErrSize ) );
                msgSender.addPart( stdErr.get(), stdErrSize );
                msgSender.send( sock );
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
            assert( receiver.parts() == 4 );
            char const * retcode;
            std::size_t retcodeSize;
            receiver.getPart( 1, &retcode, &retcodeSize );

            char * buffer = static_cast<char *>( _alloca( retcodeSize + 1 ) );
            std::memcpy( buffer, retcode, retcodeSize );
            buffer[ retcodeSize ] = 0;
            int result;
            if ( !parse( buffer, boost::spirit::int_, result ) )
            {
                std::cerr << "Failed to parse exit code.\n";
                result = -1;
            }

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
        else if ( ( requestSize == 12 ) && strncmp( request, "LOCATE_FILES", 12 ) == 0 )
        {
            assert( receiver.parts() > 1 );
            std::vector<std::string> files;
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
                msgSender.addPart( files.back().c_str(), files.back().size() );
            }
            msgSender.send( sock );
        }
        else
        {
            std::cout << "ERROR: GOT " << std::string( request, requestSize );
            return -1;
        }
    }

    return 0;
}