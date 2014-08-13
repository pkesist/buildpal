#include <windows.h>
#include <intrin.h>
#include <winternl.h>
#include <psapi.h>

__forceinline wchar_t wlower( wchar_t x )
{
    return ( x >= L'A' ) && ( x <= L'Z' ) ? x - L'A' + L'a' : x;
}

__forceinline char lower( char x )
{
    return ( x >= 'A' ) && ( x <= 'Z' ) ? x - 'A' + 'a' : x;
}

__forceinline bool isKernel32( wchar_t * str, USHORT length )
{
    return
        length == 24 &&
        wlower(str[0 ]) == L'k' &&
        wlower(str[1 ]) == L'e' &&
        wlower(str[2 ]) == L'r' &&
        wlower(str[3 ]) == L'n' &&
        wlower(str[4 ]) == L'e' &&
        wlower(str[5 ]) == L'l' &&
               str[6 ]  == L'3' &&
               str[7 ]  == L'2' &&
               str[8 ]  == L'.' &&
        wlower(str[9 ]) == L'd' &&
        wlower(str[10]) == L'l' &&
        wlower(str[11]) == L'l'
    ;
}

__forceinline bool isLoadLibrary( char const * x )
{
    return
        lower(x[0 ]) == 'l' &&
        lower(x[1 ]) == 'o' &&
        lower(x[2 ]) == 'a' &&
        lower(x[3 ]) == 'd' &&
        lower(x[4 ]) == 'l' &&
        lower(x[5 ]) == 'i' &&
        lower(x[6 ]) == 'b' &&
        lower(x[7 ]) == 'r' &&
        lower(x[8 ]) == 'a' &&
        lower(x[9 ]) == 'r' &&
        lower(x[10]) == 'y' &&
        lower(x[11]) == 'a';
}

__forceinline bool isGetProcAddress( char const * x )
{
    return
        lower(x[0 ]) == 'g' &&
        lower(x[1 ]) == 'e' &&
        lower(x[2 ]) == 't' &&
        lower(x[3 ]) == 'p' &&
        lower(x[4 ]) == 'r' &&
        lower(x[5 ]) == 'o' &&
        lower(x[6 ]) == 'c' &&
        lower(x[7 ]) == 'a' &&
        lower(x[8 ]) == 'd' &&
        lower(x[9 ]) == 'd' &&
        lower(x[10]) == 'r' &&
        lower(x[11]) == 'e' &&
        lower(x[12]) == 's' &&
        lower(x[13]) == 's';
}


struct RunDllParams
{
    char const * dllPath;
    char const * initFunc;
    void * initArgs;
    DWORD (__stdcall *chainFunc)( void * );
    void * chainArgs;
};

typedef HMODULE (WINAPI * LOADLIBRARYA)( char const * );
typedef FARPROC (WINAPI * GETPROCADDRESS)( HMODULE, char const * );
typedef DWORD   (WINAPI * INITFUNC)( void * );

DWORD __stdcall runDLL( void * vpparams )
{
    RunDllParams * params = (RunDllParams *)vpparams;
#ifdef _WIN64
    PPEB base = (PPEB)__readgsqword( 0x60 );
#else
    PPEB base = (PPEB)__readfsdword( 0x30 );
#endif

    PPEB_LDR_DATA baseAddress = (PPEB_LDR_DATA)base->Ldr;
    LOADLIBRARYA loadLibrary = 0;
    GETPROCADDRESS getProcAddress = 0;
    bool const needGetProcAddress = ( params->initFunc != 0 );
    PLDR_DATA_TABLE_ENTRY tableEntry  = (PLDR_DATA_TABLE_ENTRY)(baseAddress->InMemoryOrderModuleList.Flink - 1); // Leap of faith cast.
    for ( ; ; )
    {
        UNICODE_STRING const baseDLLName = *(UNICODE_STRING *)(tableEntry->Reserved4);
        if ( isKernel32( baseDLLName.Buffer, baseDLLName.Length ) )
        {
            PBYTE dllBase = (PBYTE)tableEntry->DllBase;
            PIMAGE_DOS_HEADER dos_header = (PIMAGE_DOS_HEADER)dllBase;
            PIMAGE_NT_HEADERS nt_headers = (PIMAGE_NT_HEADERS)(dllBase + dos_header->e_lfanew);
            PIMAGE_DATA_DIRECTORY data_dir = (PIMAGE_DATA_DIRECTORY)(&nt_headers->OptionalHeader.DataDirectory[ IMAGE_DIRECTORY_ENTRY_EXPORT ]);
            PIMAGE_EXPORT_DIRECTORY export_dir = (PIMAGE_EXPORT_DIRECTORY)(dllBase + data_dir->VirtualAddress);
            DWORD * nameArray = (DWORD *)(dllBase + export_dir->AddressOfNames);
            WORD * ordArray = (WORD *)( dllBase + export_dir->AddressOfNameOrdinals);
            unsigned int counter( 0 );
            while ( ( counter < export_dir->NumberOfFunctions ) &&
                ( !loadLibrary || ( needGetProcAddress && !getProcAddress ) ) )
            {
                char const * name = (char const *)(dllBase + *nameArray);
                bool const gpa = needGetProcAddress && isGetProcAddress( name );
                bool const ll = isLoadLibrary( name );
                if ( gpa || ll )
                {
                    DWORD * address = (DWORD *)(dllBase + export_dir->AddressOfFunctions);
                    address += *ordArray;
                    if ( ll )
                        loadLibrary = (LOADLIBRARYA)(dllBase + *address);
                    else
                        getProcAddress = (GETPROCADDRESS)(dllBase + *address);
                }
                ++nameArray;
                ++ordArray;
                ++counter;
            }
            break;
        }
        if ( tableEntry->InMemoryOrderLinks.Flink == 0 )
            break;
        tableEntry = (PLDR_DATA_TABLE_ENTRY)(tableEntry->InMemoryOrderLinks.Flink - 1);
    }
    if ( !loadLibrary )
        return -2;
    if ( needGetProcAddress && !getProcAddress )
        return -3;
    HMODULE mydll = loadLibrary( params->dllPath );
    if ( !mydll )
        return -4;
    if ( params->initFunc )
    {
        INITFUNC initFunc = (INITFUNC)getProcAddress( mydll, params->initFunc );
        if ( !initFunc )
            return -5;
        if ( initFunc( params->initArgs ) != 0 )
            return -6;
    }
    if ( params->chainFunc )
        return params->chainFunc( params->chainArgs );
    return 0;
}

int main()
{
    RunDllParams params = { 0 };
    params.dllPath = "kernel32.dll";
    return runDLL( &params );
}