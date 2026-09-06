import sys
import uvicorn

if len(sys.argv)>1 and sys.argv[1]=='mock':
    raise SystemExit('Production launcher does not start simulation')
uvicorn.run('main:app',host='127.0.0.1',port=8000,reload=False)
