
from fastapi import FastAPI
import asyncio, random

app=FastAPI(title="Hearthmind")

world={
 "tick":0,
 "season":"Spring",
 "weather":"Clear",
 "temperature":15.0,
 "day":1,
 "hour":8
}

SEASONS=["Spring","Summer","Autumn","Winter"]
WEATHER={
 "Spring":["Clear","Rain","Cloudy"],
 "Summer":["Clear","Hot","Storm"],
 "Autumn":["Cloudy","Rain","Wind"],
 "Winter":["Snow","Cloudy","Clear"]
}

async def loop():
    while True:
        world["tick"]+=1
        world["hour"]+=1
        if world["hour"]>=24:
            world["hour"]=0
            world["day"]+=1
            if world["day"]%30==0:
                idx=(SEASONS.index(world["season"])+1)%4
                world["season"]=SEASONS[idx]
        world["weather"]=random.choice(WEATHER[world["season"]])
        await asyncio.sleep(1)

@app.on_event("startup")
async def startup():
    asyncio.create_task(loop())

@app.get("/api/world")
def api():
    return world

@app.get("/")
def root():
    return {"name":"Hearthmind","version":"0.0.2","world":world}
