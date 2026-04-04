# UTF-8
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(2, 7, 2, 1),
        prodvers=(2, 7, 2, 1),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,          # VOS_NT_WINDOWS32
        fileType=0x1,        # VFT_APP
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Bob van Mierlo"),
                        StringStruct("FileDescription", "PACS Admin Tool - DICOM & HL7 Administration"),
                        StringStruct("FileVersion", "2.7.2.1"),
                        StringStruct("InternalName", "PacsAdminTool"),
                        StringStruct("LegalCopyright", "Copyright © 2025 Bob van Mierlo. Licensed under Apache-2.0."),
                        StringStruct("OriginalFilename", "PacsAdminTool.exe"),
                        StringStruct("ProductName", "PACS Admin Tool"),
                        StringStruct("ProductVersion", "2.7.2.1"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)
