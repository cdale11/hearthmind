from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path
import asyncio,time

ROOT=Path(__file__).resolve().parents[2]
templates=Jinja2Templates(directory=str(ROOT/"templates"))
app=FastAPI(title="Hearthmind")

world={"tick":0,"day":1,"hour":8,"season":"Spring","started":time.time()}

async def kernel():
    while True:
        world["tick"]+=1
        world["hour"]+=1
        if world["hour"]>=24:
            world["hour"]=0
            world["day"]+=1
        await asyncio.sleep(1)

@app.on_event("startup")
async def startup():
    asyncio.create_task(kernel())

@app.get("/",response_class=HTMLResponse)
async def index(request:Request):
    return templates.TemplateResponse(request,"index.html",{"world":world})

@app.get("/api/status")
async def status():
    return world
