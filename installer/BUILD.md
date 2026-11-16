# Setup.exe бэлтгэх (хөгжүүлэгчид)

Linux (Ubuntu) дээр Wine шаардлагагүйгээр бүтээнэ:

1. Windows Python 3.12 орчин: conda-forge-оос `python`, `libpython`, `openssl 3.5.x`, `vc14_runtime`, `ucrt`, `libffi`,
   `libsqlite`, `libzlib`, `liblzma`, `bzip2`, `libexpat` багцуудыг (`win-64`) татаж `stage/python/`-д задлана
2. `pip download --platform win_amd64 --python-version 3.12 --only-binary=:all: -r requirements.txt` →
   wheel-үүдийг `stage/python/Lib/site-packages/`-д задлана (+ `pywin32-ctypes`)
3. `stage/app/` ← `terre/`, `web/`, `config.example.yaml`, `README.md`, хоосон `installed.flag`
4. `sudo apt install nsis` → `makensis launcher.nsi && makensis installer.nsi`
   (`.nsi` файлууд UTF-8 BOM-той байх ёстой, `Target amd64-unicode`)

Суулгасан хувилбар тохиргоо, өгөгдлөө `%APPDATA%\Terre System\`-д хадгална (`installed.flag` байгаа үед).
