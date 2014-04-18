////////////////////////////////////////////////////////////////////////////////
//
// Automatically generated - do not edit
//
////////////////////////////////////////////////////////////////////////////////
// ?runDLL@@YAKPEAX@Z PROC					; runDLL
// 
// ; 82   : {
// 
// $LN197:
0x48, 0x89, 0x5c, 0x24, 0x08,                          // 00000 -  mov	 QWORD PTR [rsp+8], rbx
0x48, 0x89, 0x6c, 0x24, 0x10,                          // 00005 -  mov	 QWORD PTR [rsp+16], rbp
0x48, 0x89, 0x74, 0x24, 0x18,                          // 0000a -  mov	 QWORD PTR [rsp+24], rsi
0x57,                                                  // 0000f -  push	 rdi
0x41, 0x54,                                            // 00010 -  push	 r12
0x41, 0x55,                                            // 00012 -  push	 r13
0x41, 0x56,                                            // 00014 -  push	 r14
0x41, 0x57,                                            // 00016 -  push	 r15
0x48, 0x83, 0xec, 0x30,                                // 00018 -  sub	 rsp, 48			; 00000030H
// 
// ; 83   :     RunDllParams * params = (RunDllParams *)vpparams;
// ; 84   : #ifdef _WIN64
// ; 85   :     PPEB base = (PPEB)__readgsqword( 0x60 );
// 
0x65, 0x48, 0x8b, 0x04, 0x25, 0x60, 0x00, 0x00, 0x00,  // 0001c -  mov	 rax, QWORD PTR gs:96
// 
// ; 86   : #else
// ; 87   :     PPEB base = (PPEB)__readfsdword( 0x30 );
// ; 88   : #endif
// ; 89   : 
// ; 90   :     PPEB_LDR_DATA baseAddress = (PPEB_LDR_DATA)base->Ldr;
// ; 91   :     LOADLIBRARYA loadLibrary = 0;
// 
0x45, 0x33, 0xf6,                                      // 00025 -  xor	 r14d, r14d
0x4c, 0x8b, 0xe9,                                      // 00028 -  mov	 r13, rcx
// 
// ; 92   :     GETPROCADDRESS getProcAddress = 0;
// ; 93   :     bool const needGetProcAddress = ( params->initFunc != 0 );
// 
0x4c, 0x39, 0x71, 0x08,                                // 0002b -  cmp	 QWORD PTR [rcx+8], r14
// 
// ; 94   :     PLDR_DATA_TABLE_ENTRY tableEntry  = (PLDR_DATA_TABLE_ENTRY)(baseAddress->InMemoryOrderModuleList.Flink - 1); // Leap of faith cast.
// 
0x48, 0x8b, 0x50, 0x18,                                // 0002f -  mov	 rdx, QWORD PTR [rax+24]
0x45, 0x8b, 0xfe,                                      // 00033 -  mov	 r15d, r14d
0x4c, 0x8b, 0x42, 0x20,                                // 00036 -  mov	 r8, QWORD PTR [rdx+32]
0x41, 0x0f, 0x95, 0xc4,                                // 0003a -  setne	 r12b
0x49, 0x83, 0xe8, 0x10,                                // 0003e -  sub	 r8, 16
// 
// ; 95   :     while ( tableEntry )
// 
0x0f, 0x84, 0x6e, 0x01, 0x00, 0x00,                    // 00042 -  je	 $LN192@runDLL
0x0f, 0x1f, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00,        // 00048 -  npad	 8
// $LL17@runDLL:
// 
// ; 96   :     {
// ; 97   :         UNICODE_STRING const baseDLLName = *(UNICODE_STRING *)(tableEntry->Reserved4);
// 
0x49, 0x8b, 0x40, 0x58,                                // 00050 -  mov	 rax, QWORD PTR [r8+88]
0x49, 0x8b, 0x48, 0x60,                                // 00054 -  mov	 rcx, QWORD PTR [r8+96]
// 
// ; 98   :         if ( isKernel32( baseDLLName.Buffer ) )
// 
0x0f, 0xb7, 0x11,                                      // 00058 -  movzx	 edx, WORD PTR [rcx]
0x48, 0x89, 0x44, 0x24, 0x20,                          // 0005b -  mov	 QWORD PTR baseDLLName$1[rsp], rax
0x8d, 0x42, 0xbf,                                      // 00060 -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 00063 -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 00067 -  movzx	 eax, dx
0x77, 0x03,                                            // 0006a -  ja	 SHORT $LN27@runDLL
0x83, 0xc0, 0x20,                                      // 0006c -  add	 eax, 32			; 00000020H
// $LN27@runDLL:
0x66, 0x83, 0xf8, 0x6b,                                // 0006f -  cmp	 ax, 107			; 0000006bH
0x0f, 0x85, 0x27, 0x01, 0x00, 0x00,                    // 00073 -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x02,                                // 00079 -  movzx	 edx, WORD PTR [rcx+2]
0x8d, 0x42, 0xbf,                                      // 0007d -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 00080 -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 00084 -  movzx	 eax, dx
0x77, 0x03,                                            // 00087 -  ja	 SHORT $LN31@runDLL
0x83, 0xc0, 0x20,                                      // 00089 -  add	 eax, 32			; 00000020H
// $LN31@runDLL:
0x66, 0x83, 0xf8, 0x65,                                // 0008c -  cmp	 ax, 101			; 00000065H
0x0f, 0x85, 0x0a, 0x01, 0x00, 0x00,                    // 00090 -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x04,                                // 00096 -  movzx	 edx, WORD PTR [rcx+4]
0x8d, 0x42, 0xbf,                                      // 0009a -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 0009d -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 000a1 -  movzx	 eax, dx
0x77, 0x03,                                            // 000a4 -  ja	 SHORT $LN35@runDLL
0x83, 0xc0, 0x20,                                      // 000a6 -  add	 eax, 32			; 00000020H
// $LN35@runDLL:
0x66, 0x83, 0xf8, 0x72,                                // 000a9 -  cmp	 ax, 114			; 00000072H
0x0f, 0x85, 0xed, 0x00, 0x00, 0x00,                    // 000ad -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x06,                                // 000b3 -  movzx	 edx, WORD PTR [rcx+6]
0x8d, 0x42, 0xbf,                                      // 000b7 -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 000ba -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 000be -  movzx	 eax, dx
0x77, 0x03,                                            // 000c1 -  ja	 SHORT $LN39@runDLL
0x83, 0xc0, 0x20,                                      // 000c3 -  add	 eax, 32			; 00000020H
// $LN39@runDLL:
0x66, 0x83, 0xf8, 0x6e,                                // 000c6 -  cmp	 ax, 110			; 0000006eH
0x0f, 0x85, 0xd0, 0x00, 0x00, 0x00,                    // 000ca -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x08,                                // 000d0 -  movzx	 edx, WORD PTR [rcx+8]
0x8d, 0x42, 0xbf,                                      // 000d4 -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 000d7 -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 000db -  movzx	 eax, dx
0x77, 0x03,                                            // 000de -  ja	 SHORT $LN43@runDLL
0x83, 0xc0, 0x20,                                      // 000e0 -  add	 eax, 32			; 00000020H
// $LN43@runDLL:
0x66, 0x83, 0xf8, 0x65,                                // 000e3 -  cmp	 ax, 101			; 00000065H
0x0f, 0x85, 0xb3, 0x00, 0x00, 0x00,                    // 000e7 -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x0a,                                // 000ed -  movzx	 edx, WORD PTR [rcx+10]
0x8d, 0x42, 0xbf,                                      // 000f1 -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 000f4 -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 000f8 -  movzx	 eax, dx
0x77, 0x03,                                            // 000fb -  ja	 SHORT $LN47@runDLL
0x83, 0xc0, 0x20,                                      // 000fd -  add	 eax, 32			; 00000020H
// $LN47@runDLL:
0x66, 0x83, 0xf8, 0x6c,                                // 00100 -  cmp	 ax, 108			; 0000006cH
0x0f, 0x85, 0x96, 0x00, 0x00, 0x00,                    // 00104 -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x0c,                                // 0010a -  movzx	 edx, WORD PTR [rcx+12]
0x8d, 0x42, 0xbf,                                      // 0010e -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 00111 -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 00115 -  movzx	 eax, dx
0x77, 0x03,                                            // 00118 -  ja	 SHORT $LN51@runDLL
0x83, 0xc0, 0x20,                                      // 0011a -  add	 eax, 32			; 00000020H
// $LN51@runDLL:
0x66, 0x83, 0xf8, 0x33,                                // 0011d -  cmp	 ax, 51			; 00000033H
0x75, 0x7d,                                            // 00121 -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x51, 0x0e,                                // 00123 -  movzx	 edx, WORD PTR [rcx+14]
0x8d, 0x42, 0xbf,                                      // 00127 -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 0012a -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 0012e -  movzx	 eax, dx
0x77, 0x03,                                            // 00131 -  ja	 SHORT $LN55@runDLL
0x83, 0xc0, 0x20,                                      // 00133 -  add	 eax, 32			; 00000020H
// $LN55@runDLL:
0x66, 0x83, 0xf8, 0x32,                                // 00136 -  cmp	 ax, 50			; 00000032H
0x75, 0x64,                                            // 0013a -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x51, 0x10,                                // 0013c -  movzx	 edx, WORD PTR [rcx+16]
0x8d, 0x42, 0xbf,                                      // 00140 -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 00143 -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 00147 -  movzx	 eax, dx
0x77, 0x03,                                            // 0014a -  ja	 SHORT $LN59@runDLL
0x83, 0xc0, 0x20,                                      // 0014c -  add	 eax, 32			; 00000020H
// $LN59@runDLL:
0x66, 0x83, 0xf8, 0x2e,                                // 0014f -  cmp	 ax, 46			; 0000002eH
0x75, 0x4b,                                            // 00153 -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x51, 0x12,                                // 00155 -  movzx	 edx, WORD PTR [rcx+18]
0x8d, 0x42, 0xbf,                                      // 00159 -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 0015c -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 00160 -  movzx	 eax, dx
0x77, 0x03,                                            // 00163 -  ja	 SHORT $LN63@runDLL
0x83, 0xc0, 0x20,                                      // 00165 -  add	 eax, 32			; 00000020H
// $LN63@runDLL:
0x66, 0x83, 0xf8, 0x64,                                // 00168 -  cmp	 ax, 100			; 00000064H
0x75, 0x32,                                            // 0016c -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x51, 0x14,                                // 0016e -  movzx	 edx, WORD PTR [rcx+20]
0x8d, 0x42, 0xbf,                                      // 00172 -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 00175 -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 00179 -  movzx	 eax, dx
0x77, 0x03,                                            // 0017c -  ja	 SHORT $LN67@runDLL
0x83, 0xc0, 0x20,                                      // 0017e -  add	 eax, 32			; 00000020H
// $LN67@runDLL:
0x66, 0x83, 0xf8, 0x6c,                                // 00181 -  cmp	 ax, 108			; 0000006cH
0x75, 0x19,                                            // 00185 -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x51, 0x16,                                // 00187 -  movzx	 edx, WORD PTR [rcx+22]
0x8d, 0x42, 0xbf,                                      // 0018b -  lea	 eax, DWORD PTR [rdx-65]
0x66, 0x83, 0xf8, 0x19,                                // 0018e -  cmp	 ax, 25
0x0f, 0xb7, 0xc2,                                      // 00192 -  movzx	 eax, dx
0x77, 0x03,                                            // 00195 -  ja	 SHORT $LN71@runDLL
0x83, 0xc0, 0x20,                                      // 00197 -  add	 eax, 32			; 00000020H
// $LN71@runDLL:
0x66, 0x83, 0xf8, 0x6c,                                // 0019a -  cmp	 ax, 108			; 0000006cH
0x74, 0x38,                                            // 0019e -  je	 SHORT $LN186@runDLL
// $LN22@runDLL:
// 
// ; 126  :             }
// ; 127  :             break;
// ; 128  :         }
// ; 129  :         if ( tableEntry->InMemoryOrderLinks.Flink == 0 )
// 
0x49, 0x8b, 0x40, 0x10,                                // 001a0 -  mov	 rax, QWORD PTR [r8+16]
0x48, 0x85, 0xc0,                                      // 001a4 -  test	 rax, rax
0x74, 0x0d,                                            // 001a7 -  je	 SHORT $LN192@runDLL
// 
// ; 130  :             break;
// ; 131  :         tableEntry = (PLDR_DATA_TABLE_ENTRY)(tableEntry->InMemoryOrderLinks.Flink - 1);
// 
0x4c, 0x8d, 0x40, 0xf0,                                // 001a9 -  lea	 r8, QWORD PTR [rax-16]
0x4d, 0x85, 0xc0,                                      // 001ad -  test	 r8, r8
0x0f, 0x85, 0x9a, 0xfe, 0xff, 0xff,                    // 001b0 -  jne	 $LL17@runDLL
// $LN192@runDLL:
// 
// ; 134  :         return -2;
// 
0xb8, 0xfe, 0xff, 0xff, 0xff,                          // 001b6 -  mov	 eax, -2			; fffffffeH
// $LN18@runDLL:
// 
// ; 149  : }
// 
0x48, 0x8b, 0x5c, 0x24, 0x60,                          // 001bb -  mov	 rbx, QWORD PTR [rsp+96]
0x48, 0x8b, 0x6c, 0x24, 0x68,                          // 001c0 -  mov	 rbp, QWORD PTR [rsp+104]
0x48, 0x8b, 0x74, 0x24, 0x70,                          // 001c5 -  mov	 rsi, QWORD PTR [rsp+112]
0x48, 0x83, 0xc4, 0x30,                                // 001ca -  add	 rsp, 48			; 00000030H
0x41, 0x5f,                                            // 001ce -  pop	 r15
0x41, 0x5e,                                            // 001d0 -  pop	 r14
0x41, 0x5d,                                            // 001d2 -  pop	 r13
0x41, 0x5c,                                            // 001d4 -  pop	 r12
0x5f,                                                  // 001d6 -  pop	 rdi
0xc3,                                                  // 001d7 -  ret	 0
// $LN186@runDLL:
// 
// ; 99   :         {
// ; 100  :             PBYTE dllBase = (PBYTE)tableEntry->DllBase;
// 
0x4d, 0x8b, 0x50, 0x30,                                // 001d8 -  mov	 r10, QWORD PTR [r8+48]
// 
// ; 101  :             PIMAGE_DOS_HEADER dos_header = (PIMAGE_DOS_HEADER)dllBase;
// ; 102  :             PIMAGE_NT_HEADERS nt_headers = (PIMAGE_NT_HEADERS)(dllBase + dos_header->e_lfanew);
// ; 103  :             PIMAGE_DATA_DIRECTORY data_dir = (PIMAGE_DATA_DIRECTORY)(&nt_headers->OptionalHeader.DataDirectory[ IMAGE_DIRECTORY_ENTRY_EXPORT ]);
// ; 104  :             PIMAGE_EXPORT_DIRECTORY export_dir = (PIMAGE_EXPORT_DIRECTORY)(dllBase + data_dir->VirtualAddress);
// ; 105  :             DWORD * nameArray = (DWORD *)(dllBase + export_dir->AddressOfNames);
// ; 106  :             WORD * ordArray = (WORD *)( dllBase + export_dir->AddressOfNameOrdinals);
// ; 107  :             unsigned int counter( 0 );
// 
0x45, 0x8b, 0xde,                                      // 001dc -  mov	 r11d, r14d
0x49, 0x63, 0x42, 0x3c,                                // 001df -  movsxd	 rax, DWORD PTR [r10+60]
0x42, 0x8b, 0xac, 0x10, 0x88, 0x00, 0x00, 0x00,        // 001e3 -  mov	 ebp, DWORD PTR [rax+r10+136]
0x49, 0x03, 0xea,                                      // 001eb -  add	 rbp, r10
0x8b, 0x5d, 0x20,                                      // 001ee -  mov	 ebx, DWORD PTR [rbp+32]
0x8b, 0x7d, 0x24,                                      // 001f1 -  mov	 edi, DWORD PTR [rbp+36]
0x8b, 0x75, 0x14,                                      // 001f4 -  mov	 esi, DWORD PTR [rbp+20]
0x49, 0x03, 0xda,                                      // 001f7 -  add	 rbx, r10
0x49, 0x03, 0xfa,                                      // 001fa -  add	 rdi, r10
// 
// ; 108  :             while ( ( counter < export_dir->NumberOfFunctions ) &&
// ; 109  :                 ( !loadLibrary || ( needGetProcAddress && !getProcAddress ) ) )
// 
0x85, 0xf6,                                            // 001fd -  test	 esi, esi
0x74, 0xb5,                                            // 001ff -  je	 SHORT $LN192@runDLL
// $LL14@runDLL:
0x4d, 0x85, 0xf6,                                      // 00201 -  test	 r14, r14
0x74, 0x12,                                            // 00204 -  je	 SHORT $LN12@runDLL
0x45, 0x84, 0xe4,                                      // 00206 -  test	 r12b, r12b
0x0f, 0x84, 0xb9, 0x02, 0x00, 0x00,                    // 00209 -  je	 $LN13@runDLL
0x4d, 0x85, 0xff,                                      // 0020f -  test	 r15, r15
0x0f, 0x85, 0xb0, 0x02, 0x00, 0x00,                    // 00212 -  jne	 $LN13@runDLL
// $LN12@runDLL:
// 
// ; 110  :             {
// ; 111  :                 char const * name = (char const *)(dllBase + *nameArray);
// 
0x8b, 0x13,                                            // 00218 -  mov	 edx, DWORD PTR [rbx]
0x49, 0x03, 0xd2,                                      // 0021a -  add	 rdx, r10
// 
// ; 112  :                 bool const gpa = isGetProcAddress( name );
// 
0x44, 0x0f, 0xb6, 0x02,                                // 0021d -  movzx	 r8d, BYTE PTR [rdx]
0x41, 0x8d, 0x40, 0xbf,                                // 00221 -  lea	 eax, DWORD PTR [r8-65]
0x3c, 0x19,                                            // 00225 -  cmp	 al, 25
0x41, 0x0f, 0xbe, 0xc0,                                // 00227 -  movsx	 eax, r8b
0x77, 0x03,                                            // 0022b -  ja	 SHORT $LN79@runDLL
0x83, 0xc0, 0x20,                                      // 0022d -  add	 eax, 32			; 00000020H
// $LN79@runDLL:
0x3c, 0x67,                                            // 00230 -  cmp	 al, 103			; 00000067H
0x0f, 0x85, 0x32, 0x01, 0x00, 0x00,                    // 00232 -  jne	 $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x01,                                // 00238 -  movzx	 ecx, BYTE PTR [rdx+1]
0x8d, 0x41, 0xbf,                                      // 0023c -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 0023f -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 00241 -  movsx	 eax, cl
0x77, 0x03,                                            // 00244 -  ja	 SHORT $LN83@runDLL
0x83, 0xc0, 0x20,                                      // 00246 -  add	 eax, 32			; 00000020H
// $LN83@runDLL:
0x3c, 0x65,                                            // 00249 -  cmp	 al, 101			; 00000065H
0x0f, 0x85, 0x19, 0x01, 0x00, 0x00,                    // 0024b -  jne	 $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x02,                                // 00251 -  movzx	 ecx, BYTE PTR [rdx+2]
0x8d, 0x41, 0xbf,                                      // 00255 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00258 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 0025a -  movsx	 eax, cl
0x77, 0x03,                                            // 0025d -  ja	 SHORT $LN87@runDLL
0x83, 0xc0, 0x20,                                      // 0025f -  add	 eax, 32			; 00000020H
// $LN87@runDLL:
0x3c, 0x74,                                            // 00262 -  cmp	 al, 116			; 00000074H
0x0f, 0x85, 0x00, 0x01, 0x00, 0x00,                    // 00264 -  jne	 $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x03,                                // 0026a -  movzx	 ecx, BYTE PTR [rdx+3]
0x8d, 0x41, 0xbf,                                      // 0026e -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00271 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 00273 -  movsx	 eax, cl
0x77, 0x03,                                            // 00276 -  ja	 SHORT $LN91@runDLL
0x83, 0xc0, 0x20,                                      // 00278 -  add	 eax, 32			; 00000020H
// $LN91@runDLL:
0x3c, 0x70,                                            // 0027b -  cmp	 al, 112			; 00000070H
0x0f, 0x85, 0xe7, 0x00, 0x00, 0x00,                    // 0027d -  jne	 $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x04,                                // 00283 -  movzx	 ecx, BYTE PTR [rdx+4]
0x8d, 0x41, 0xbf,                                      // 00287 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 0028a -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 0028c -  movsx	 eax, cl
0x77, 0x03,                                            // 0028f -  ja	 SHORT $LN95@runDLL
0x83, 0xc0, 0x20,                                      // 00291 -  add	 eax, 32			; 00000020H
// $LN95@runDLL:
0x3c, 0x72,                                            // 00294 -  cmp	 al, 114			; 00000072H
0x0f, 0x85, 0xce, 0x00, 0x00, 0x00,                    // 00296 -  jne	 $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x05,                                // 0029c -  movzx	 ecx, BYTE PTR [rdx+5]
0x8d, 0x41, 0xbf,                                      // 002a0 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 002a3 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 002a5 -  movsx	 eax, cl
0x77, 0x03,                                            // 002a8 -  ja	 SHORT $LN99@runDLL
0x83, 0xc0, 0x20,                                      // 002aa -  add	 eax, 32			; 00000020H
// $LN99@runDLL:
0x3c, 0x6f,                                            // 002ad -  cmp	 al, 111			; 0000006fH
0x0f, 0x85, 0xb5, 0x00, 0x00, 0x00,                    // 002af -  jne	 $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x06,                                // 002b5 -  movzx	 ecx, BYTE PTR [rdx+6]
0x8d, 0x41, 0xbf,                                      // 002b9 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 002bc -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 002be -  movsx	 eax, cl
0x77, 0x03,                                            // 002c1 -  ja	 SHORT $LN103@runDLL
0x83, 0xc0, 0x20,                                      // 002c3 -  add	 eax, 32			; 00000020H
// $LN103@runDLL:
0x3c, 0x63,                                            // 002c6 -  cmp	 al, 99			; 00000063H
0x0f, 0x85, 0x9c, 0x00, 0x00, 0x00,                    // 002c8 -  jne	 $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x07,                                // 002ce -  movzx	 ecx, BYTE PTR [rdx+7]
0x8d, 0x41, 0xbf,                                      // 002d2 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 002d5 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 002d7 -  movsx	 eax, cl
0x77, 0x03,                                            // 002da -  ja	 SHORT $LN107@runDLL
0x83, 0xc0, 0x20,                                      // 002dc -  add	 eax, 32			; 00000020H
// $LN107@runDLL:
0x3c, 0x61,                                            // 002df -  cmp	 al, 97			; 00000061H
0x0f, 0x85, 0x83, 0x00, 0x00, 0x00,                    // 002e1 -  jne	 $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x08,                                // 002e7 -  movzx	 ecx, BYTE PTR [rdx+8]
0x8d, 0x41, 0xbf,                                      // 002eb -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 002ee -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 002f0 -  movsx	 eax, cl
0x77, 0x03,                                            // 002f3 -  ja	 SHORT $LN111@runDLL
0x83, 0xc0, 0x20,                                      // 002f5 -  add	 eax, 32			; 00000020H
// $LN111@runDLL:
0x3c, 0x64,                                            // 002f8 -  cmp	 al, 100			; 00000064H
0x75, 0x6e,                                            // 002fa -  jne	 SHORT $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x09,                                // 002fc -  movzx	 ecx, BYTE PTR [rdx+9]
0x8d, 0x41, 0xbf,                                      // 00300 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00303 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 00305 -  movsx	 eax, cl
0x77, 0x03,                                            // 00308 -  ja	 SHORT $LN115@runDLL
0x83, 0xc0, 0x20,                                      // 0030a -  add	 eax, 32			; 00000020H
// $LN115@runDLL:
0x3c, 0x64,                                            // 0030d -  cmp	 al, 100			; 00000064H
0x75, 0x59,                                            // 0030f -  jne	 SHORT $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x0a,                                // 00311 -  movzx	 ecx, BYTE PTR [rdx+10]
0x8d, 0x41, 0xbf,                                      // 00315 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00318 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 0031a -  movsx	 eax, cl
0x77, 0x03,                                            // 0031d -  ja	 SHORT $LN119@runDLL
0x83, 0xc0, 0x20,                                      // 0031f -  add	 eax, 32			; 00000020H
// $LN119@runDLL:
0x3c, 0x72,                                            // 00322 -  cmp	 al, 114			; 00000072H
0x75, 0x44,                                            // 00324 -  jne	 SHORT $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x0b,                                // 00326 -  movzx	 ecx, BYTE PTR [rdx+11]
0x8d, 0x41, 0xbf,                                      // 0032a -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 0032d -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 0032f -  movsx	 eax, cl
0x77, 0x03,                                            // 00332 -  ja	 SHORT $LN123@runDLL
0x83, 0xc0, 0x20,                                      // 00334 -  add	 eax, 32			; 00000020H
// $LN123@runDLL:
0x3c, 0x65,                                            // 00337 -  cmp	 al, 101			; 00000065H
0x75, 0x2f,                                            // 00339 -  jne	 SHORT $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x0c,                                // 0033b -  movzx	 ecx, BYTE PTR [rdx+12]
0x8d, 0x41, 0xbf,                                      // 0033f -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00342 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 00344 -  movsx	 eax, cl
0x77, 0x03,                                            // 00347 -  ja	 SHORT $LN127@runDLL
0x83, 0xc0, 0x20,                                      // 00349 -  add	 eax, 32			; 00000020H
// $LN127@runDLL:
0x3c, 0x73,                                            // 0034c -  cmp	 al, 115			; 00000073H
0x75, 0x1a,                                            // 0034e -  jne	 SHORT $LN74@runDLL
0x0f, 0xb6, 0x4a, 0x0d,                                // 00350 -  movzx	 ecx, BYTE PTR [rdx+13]
0x8d, 0x41, 0xbf,                                      // 00354 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00357 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 00359 -  movsx	 eax, cl
0x77, 0x03,                                            // 0035c -  ja	 SHORT $LN131@runDLL
0x83, 0xc0, 0x20,                                      // 0035e -  add	 eax, 32			; 00000020H
// $LN131@runDLL:
0x3c, 0x73,                                            // 00361 -  cmp	 al, 115			; 00000073H
0x75, 0x05,                                            // 00363 -  jne	 SHORT $LN74@runDLL
0x41, 0xb1, 0x01,                                      // 00365 -  mov	 r9b, 1
0xeb, 0x03,                                            // 00368 -  jmp	 SHORT $LN75@runDLL
// $LN74@runDLL:
0x45, 0x32, 0xc9,                                      // 0036a -  xor	 r9b, r9b
// $LN75@runDLL:
// 
// ; 113  :                 bool const ll = isLoadLibrary( name );
// 
0x41, 0x8d, 0x40, 0xbf,                                // 0036d -  lea	 eax, DWORD PTR [r8-65]
0x3c, 0x19,                                            // 00371 -  cmp	 al, 25
0x41, 0x0f, 0xbe, 0xc0,                                // 00373 -  movsx	 eax, r8b
0x77, 0x03,                                            // 00377 -  ja	 SHORT $LN139@runDLL
0x83, 0xc0, 0x20,                                      // 00379 -  add	 eax, 32			; 00000020H
// $LN139@runDLL:
0x3c, 0x6c,                                            // 0037c -  cmp	 al, 108			; 0000006cH
0x0f, 0x85, 0x00, 0x01, 0x00, 0x00,                    // 0037e -  jne	 $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x01,                                // 00384 -  movzx	 ecx, BYTE PTR [rdx+1]
0x8d, 0x41, 0xbf,                                      // 00388 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 0038b -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 0038d -  movsx	 eax, cl
0x77, 0x03,                                            // 00390 -  ja	 SHORT $LN143@runDLL
0x83, 0xc0, 0x20,                                      // 00392 -  add	 eax, 32			; 00000020H
// $LN143@runDLL:
0x3c, 0x6f,                                            // 00395 -  cmp	 al, 111			; 0000006fH
0x0f, 0x85, 0xe7, 0x00, 0x00, 0x00,                    // 00397 -  jne	 $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x02,                                // 0039d -  movzx	 ecx, BYTE PTR [rdx+2]
0x8d, 0x41, 0xbf,                                      // 003a1 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 003a4 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 003a6 -  movsx	 eax, cl
0x77, 0x03,                                            // 003a9 -  ja	 SHORT $LN147@runDLL
0x83, 0xc0, 0x20,                                      // 003ab -  add	 eax, 32			; 00000020H
// $LN147@runDLL:
0x3c, 0x61,                                            // 003ae -  cmp	 al, 97			; 00000061H
0x0f, 0x85, 0xce, 0x00, 0x00, 0x00,                    // 003b0 -  jne	 $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x03,                                // 003b6 -  movzx	 ecx, BYTE PTR [rdx+3]
0x8d, 0x41, 0xbf,                                      // 003ba -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 003bd -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 003bf -  movsx	 eax, cl
0x77, 0x03,                                            // 003c2 -  ja	 SHORT $LN151@runDLL
0x83, 0xc0, 0x20,                                      // 003c4 -  add	 eax, 32			; 00000020H
// $LN151@runDLL:
0x3c, 0x64,                                            // 003c7 -  cmp	 al, 100			; 00000064H
0x0f, 0x85, 0xb5, 0x00, 0x00, 0x00,                    // 003c9 -  jne	 $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x04,                                // 003cf -  movzx	 ecx, BYTE PTR [rdx+4]
0x8d, 0x41, 0xbf,                                      // 003d3 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 003d6 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 003d8 -  movsx	 eax, cl
0x77, 0x03,                                            // 003db -  ja	 SHORT $LN155@runDLL
0x83, 0xc0, 0x20,                                      // 003dd -  add	 eax, 32			; 00000020H
// $LN155@runDLL:
0x3c, 0x6c,                                            // 003e0 -  cmp	 al, 108			; 0000006cH
0x0f, 0x85, 0x9c, 0x00, 0x00, 0x00,                    // 003e2 -  jne	 $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x05,                                // 003e8 -  movzx	 ecx, BYTE PTR [rdx+5]
0x8d, 0x41, 0xbf,                                      // 003ec -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 003ef -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 003f1 -  movsx	 eax, cl
0x77, 0x03,                                            // 003f4 -  ja	 SHORT $LN159@runDLL
0x83, 0xc0, 0x20,                                      // 003f6 -  add	 eax, 32			; 00000020H
// $LN159@runDLL:
0x3c, 0x69,                                            // 003f9 -  cmp	 al, 105			; 00000069H
0x0f, 0x85, 0x83, 0x00, 0x00, 0x00,                    // 003fb -  jne	 $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x06,                                // 00401 -  movzx	 ecx, BYTE PTR [rdx+6]
0x8d, 0x41, 0xbf,                                      // 00405 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00408 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 0040a -  movsx	 eax, cl
0x77, 0x03,                                            // 0040d -  ja	 SHORT $LN163@runDLL
0x83, 0xc0, 0x20,                                      // 0040f -  add	 eax, 32			; 00000020H
// $LN163@runDLL:
0x3c, 0x62,                                            // 00412 -  cmp	 al, 98			; 00000062H
0x75, 0x6e,                                            // 00414 -  jne	 SHORT $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x07,                                // 00416 -  movzx	 ecx, BYTE PTR [rdx+7]
0x8d, 0x41, 0xbf,                                      // 0041a -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 0041d -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 0041f -  movsx	 eax, cl
0x77, 0x03,                                            // 00422 -  ja	 SHORT $LN167@runDLL
0x83, 0xc0, 0x20,                                      // 00424 -  add	 eax, 32			; 00000020H
// $LN167@runDLL:
0x3c, 0x72,                                            // 00427 -  cmp	 al, 114			; 00000072H
0x75, 0x59,                                            // 00429 -  jne	 SHORT $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x08,                                // 0042b -  movzx	 ecx, BYTE PTR [rdx+8]
0x8d, 0x41, 0xbf,                                      // 0042f -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00432 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 00434 -  movsx	 eax, cl
0x77, 0x03,                                            // 00437 -  ja	 SHORT $LN171@runDLL
0x83, 0xc0, 0x20,                                      // 00439 -  add	 eax, 32			; 00000020H
// $LN171@runDLL:
0x3c, 0x61,                                            // 0043c -  cmp	 al, 97			; 00000061H
0x75, 0x44,                                            // 0043e -  jne	 SHORT $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x09,                                // 00440 -  movzx	 ecx, BYTE PTR [rdx+9]
0x8d, 0x41, 0xbf,                                      // 00444 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00447 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 00449 -  movsx	 eax, cl
0x77, 0x03,                                            // 0044c -  ja	 SHORT $LN175@runDLL
0x83, 0xc0, 0x20,                                      // 0044e -  add	 eax, 32			; 00000020H
// $LN175@runDLL:
0x3c, 0x72,                                            // 00451 -  cmp	 al, 114			; 00000072H
0x75, 0x2f,                                            // 00453 -  jne	 SHORT $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x0a,                                // 00455 -  movzx	 ecx, BYTE PTR [rdx+10]
0x8d, 0x41, 0xbf,                                      // 00459 -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 0045c -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 0045e -  movsx	 eax, cl
0x77, 0x03,                                            // 00461 -  ja	 SHORT $LN179@runDLL
0x83, 0xc0, 0x20,                                      // 00463 -  add	 eax, 32			; 00000020H
// $LN179@runDLL:
0x3c, 0x79,                                            // 00466 -  cmp	 al, 121			; 00000079H
0x75, 0x1a,                                            // 00468 -  jne	 SHORT $LN134@runDLL
0x0f, 0xb6, 0x4a, 0x0b,                                // 0046a -  movzx	 ecx, BYTE PTR [rdx+11]
0x8d, 0x41, 0xbf,                                      // 0046e -  lea	 eax, DWORD PTR [rcx-65]
0x3c, 0x19,                                            // 00471 -  cmp	 al, 25
0x0f, 0xbe, 0xc1,                                      // 00473 -  movsx	 eax, cl
0x77, 0x03,                                            // 00476 -  ja	 SHORT $LN183@runDLL
0x83, 0xc0, 0x20,                                      // 00478 -  add	 eax, 32			; 00000020H
// $LN183@runDLL:
0x3c, 0x61,                                            // 0047b -  cmp	 al, 97			; 00000061H
0x75, 0x05,                                            // 0047d -  jne	 SHORT $LN134@runDLL
0x41, 0xb0, 0x01,                                      // 0047f -  mov	 r8b, 1
0xeb, 0x03,                                            // 00482 -  jmp	 SHORT $LN135@runDLL
// $LN134@runDLL:
0x45, 0x32, 0xc0,                                      // 00484 -  xor	 r8b, r8b
// $LN135@runDLL:
// 
// ; 114  :                 if ( ( needGetProcAddress && gpa ) || ll )
// 
0x45, 0x84, 0xe4,                                      // 00487 -  test	 r12b, r12b
0x74, 0x05,                                            // 0048a -  je	 SHORT $LN9@runDLL
0x45, 0x84, 0xc9,                                      // 0048c -  test	 r9b, r9b
0x75, 0x05,                                            // 0048f -  jne	 SHORT $LN10@runDLL
// $LN9@runDLL:
0x45, 0x84, 0xc0,                                      // 00491 -  test	 r8b, r8b
0x74, 0x1e,                                            // 00494 -  je	 SHORT $LN7@runDLL
// $LN10@runDLL:
// 
// ; 115  :                 {
// ; 116  :                     DWORD * address = (DWORD *)(dllBase + export_dir->AddressOfFunctions);
// 
0x8b, 0x4d, 0x1c,                                      // 00496 -  mov	 ecx, DWORD PTR [rbp+28]
// 
// ; 117  :                     address += *ordArray;
// 
0x0f, 0xb7, 0x17,                                      // 00499 -  movzx	 edx, WORD PTR [rdi]
0x49, 0x03, 0xca,                                      // 0049c -  add	 rcx, r10
// 
// ; 118  :                     if ( ll )
// 
0x45, 0x84, 0xc0,                                      // 0049f -  test	 r8b, r8b
0x74, 0x09,                                            // 004a2 -  je	 SHORT $LN8@runDLL
// 
// ; 119  :                         loadLibrary = (LOADLIBRARYA)(dllBase + *address);
// 
0x44, 0x8b, 0x34, 0x91,                                // 004a4 -  mov	 r14d, DWORD PTR [rcx+rdx*4]
0x4d, 0x03, 0xf2,                                      // 004a8 -  add	 r14, r10
// 
// ; 120  :                     else
// 
0xeb, 0x07,                                            // 004ab -  jmp	 SHORT $LN7@runDLL
// $LN8@runDLL:
// 
// ; 121  :                         getProcAddress = (GETPROCADDRESS)(dllBase + *address);
// 
0x44, 0x8b, 0x3c, 0x91,                                // 004ad -  mov	 r15d, DWORD PTR [rcx+rdx*4]
0x4d, 0x03, 0xfa,                                      // 004b1 -  add	 r15, r10
// $LN7@runDLL:
// 
// ; 122  :                 }
// ; 123  :                 ++nameArray;
// ; 124  :                 ++ordArray;
// ; 125  :                 ++counter;
// 
0x41, 0xff, 0xc3,                                      // 004b4 -  inc	 r11d
0x48, 0x83, 0xc3, 0x04,                                // 004b7 -  add	 rbx, 4
0x48, 0x83, 0xc7, 0x02,                                // 004bb -  add	 rdi, 2
0x44, 0x3b, 0xde,                                      // 004bf -  cmp	 r11d, esi
0x0f, 0x82, 0x39, 0xfd, 0xff, 0xff,                    // 004c2 -  jb	 $LL14@runDLL
// $LN13@runDLL:
// 
// ; 132  :     }
// ; 133  :     if ( !loadLibrary )
// 
0x4d, 0x85, 0xf6,                                      // 004c8 -  test	 r14, r14
0x0f, 0x84, 0xe5, 0xfc, 0xff, 0xff,                    // 004cb -  je	 $LN192@runDLL
// 
// ; 135  :     if ( needGetProcAddress && !getProcAddress )
// 
0x45, 0x84, 0xe4,                                      // 004d1 -  test	 r12b, r12b
0x74, 0x0f,                                            // 004d4 -  je	 SHORT $LN4@runDLL
0x4d, 0x85, 0xff,                                      // 004d6 -  test	 r15, r15
0x75, 0x0a,                                            // 004d9 -  jne	 SHORT $LN4@runDLL
// 
// ; 136  :         return -3;
// 
0xb8, 0xfd, 0xff, 0xff, 0xff,                          // 004db -  mov	 eax, -3			; fffffffdH
0xe9, 0xd6, 0xfc, 0xff, 0xff,                          // 004e0 -  jmp	 $LN18@runDLL
// $LN4@runDLL:
// 
// ; 137  :     HMODULE mydll = loadLibrary( params->dllPath );
// 
0x49, 0x8b, 0x4d, 0x00,                                // 004e5 -  mov	 rcx, QWORD PTR [r13]
0x41, 0xff, 0xd6,                                      // 004e9 -  call	 r14
// 
// ; 138  :     if ( !mydll )
// 
0x48, 0x85, 0xc0,                                      // 004ec -  test	 rax, rax
0x75, 0x0a,                                            // 004ef -  jne	 SHORT $LN3@runDLL
// 
// ; 139  :         return -4;
// 
0xb8, 0xfc, 0xff, 0xff, 0xff,                          // 004f1 -  mov	 eax, -4			; fffffffcH
0xe9, 0xc0, 0xfc, 0xff, 0xff,                          // 004f6 -  jmp	 $LN18@runDLL
// $LN3@runDLL:
// 
// ; 140  :     if ( params->initFunc )
// 
0x49, 0x8b, 0x55, 0x08,                                // 004fb -  mov	 rdx, QWORD PTR [r13+8]
0x48, 0x85, 0xd2,                                      // 004ff -  test	 rdx, rdx
0x74, 0x20,                                            // 00502 -  je	 SHORT $LN2@runDLL
// 
// ; 141  :     {
// ; 142  :         typedef DWORD (WINAPI *InitFunc)( void * );
// ; 143  :         InitFunc initFunc = (InitFunc)getProcAddress( mydll, params->initFunc );
// 
0x48, 0x8b, 0xc8,                                      // 00504 -  mov	 rcx, rax
0x41, 0xff, 0xd7,                                      // 00507 -  call	 r15
// 
// ; 144  :         if ( !initFunc )
// 
0x48, 0x85, 0xc0,                                      // 0050a -  test	 rax, rax
0x75, 0x0a,                                            // 0050d -  jne	 SHORT $LN1@runDLL
// 
// ; 145  :             return -5;
// 
0xb8, 0xfb, 0xff, 0xff, 0xff,                          // 0050f -  mov	 eax, -5			; fffffffbH
0xe9, 0xa2, 0xfc, 0xff, 0xff,                          // 00514 -  jmp	 $LN18@runDLL
// $LN1@runDLL:
// 
// ; 146  :         return initFunc( params->initArgs );
// 
0x49, 0x8b, 0x4d, 0x10,                                // 00519 -  mov	 rcx, QWORD PTR [r13+16]
0xff, 0xd0,                                            // 0051d -  call	 rax
0xe9, 0x97, 0xfc, 0xff, 0xff,                          // 0051f -  jmp	 $LN18@runDLL
// $LN2@runDLL:
// 
// ; 147  :     }
// ; 148  :     return 0;
// 
0x33, 0xc0,                                            // 00524 -  xor	 eax, eax
0xe9, 0x90, 0xfc, 0xff, 0xff                           // 00526 -  jmp	 $LN18@runDLL
// ?runDLL@@YAKPEAX@Z ENDP					; runDLL
