import random
TILES=["grass","forest","hill","water"]
class Terrain:
    def __init__(self,w=64,h=64,seed=12345):
        self.w=w; self.h=h; self.seed=seed; random.seed(seed)
        self.grid=[[random.choices(TILES,[60,20,15,5])[0] for _ in range(w)] for _ in range(h)]
    def to_json(self):
        return {"width":self.w,"height":self.h,"tiles":self.grid}
