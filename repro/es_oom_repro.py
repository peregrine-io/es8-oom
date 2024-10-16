import os
import random
from time import sleep
from elasticsearch import Elasticsearch

import json
import urllib3


urllib3.disable_warnings()

# Create an Elasticsearch client with password authentication
es = Elasticsearch(
    hosts=[{"host": "localhost", "port": 9200, "use_ssl": False}],
    verify_certs=False,
    timeout=1000,
)

index = "oom-index"


def create():
    """
    Create a index to test OOM's in.
    """
    es.indices.delete(index=index, ignore=[400, 404])
    es.indices.create(
        index=index,
        ignore=400,
        body={"settings": {"codec": "best_compression"}},
    )
    mapping = {
        "properties": {"geometry": {"type": "geo_shape", "ignore_malformed": False}}
    }
    es.indices.put_mapping(body=mapping, index=index)


def do_refresh():
    es.indices.refresh(index=index)


def index_random_point():
    latitude = random.uniform(-180, 180)
    longitude = random.uniform(-90, 90)
    body = {"geometry": {
        "type": "Point",
        "coordinates": [latitude, longitude],
    }}
    es.index(index=index, body=body)


def index_point_in_search():
    """Creates a point that is within the bounds of the search query."""
    body = {
        "geometry": {
            "coordinates": [-121.97481728124649, 37.89329142322475],
            "type": "Point",
        }
    }
    es.index(index=index, body=body)

def get_directory():
    return str(os.getcwd())

def index_big_geom():
    with open(
        get_directory() + "/geometry.json", "r"
    ) as f:
        geometry = json.load(f)
    es.index(index=index, body={"geometry": geometry})

def oom_search():
    print("--------------------")
    print("Executing a search will oom")
    print("--------------------")
    with open(get_directory() + "/oom_query.json", "r") as f:
        query = json.load(f)
    print(es.search(body=query, index=index))


def exec():
    # Create the index
    create()
    # Index a point that is within the bounds of the search query
    index_point_in_search()
    # Index a bunch of points into multiple segments
    for _ in range(100):
        for _ in range(100):
            index_random_point()
        do_refresh()
    # Index a large geometry
    index_big_geom()
    do_refresh()
    sleep(1)
    # Merge the segments together
    es.indices.forcemerge(index=index, flush=True, max_num_segments=1)
    sleep(1)
    # Search causes an OOM
    oom_search()

exec()

