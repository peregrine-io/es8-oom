# Overview
This repository demonstrates an out of memory error in Elasticsearch version 8.15.

To reproduce the error you will need docker and python installed then follow these steps.
`git clone https://github.com/peregrine-io/es8-oom.git`
`cd es8-oom/repro`
`docker-compose up es8`
`pip install -r requirements.txt`
`python es_oom_repro`

This will take a few minutes to run as it indexes a very large document. After some time you will see an error from the script:
`elastic_transport.ConnectionError: Connection error caused by: ConnectionError(Connection error caused by: ProtocolError(('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')`

The docker container will report an OOM:
```
repro-es8-1  | java.lang.OutOfMemoryError: Java heap space
repro-es8-1  | Dumping heap to data/java_pid67.hprof ...
repro-es8-1  | Terminating due to java.lang.OutOfMemoryError: Java heap space
repro-es8-1  |
repro-es8-1  | ERROR: Elasticsearch exited unexpectedly, with exit code 3
repro-es8-1 exited with code 3
```

**Problem Description**
When we issue a search where the following two conditions are true, ES OOM's:
1. The index being searched contains documents with large geojson fields.
2. The query is an aggregation query and the buckets are geojson buckets using the field in 1.

In the referenced repro repository I:
1. Start ES in docker with 1GB of memory.
2. Create a new index.
3. Index some points.
4. Index a document with a large geometry.
5. Force merge (this seems to be necessary to get the right info on disk for the failure to happen).
6. Run an aggregation search against that index and geometry field.
7. OOM.

When I open up the head dump in VisualVM I see that most of the memory is taken by byte[]:
![image](https://github.com/user-attachments/assets/e55484be-7b77-42c1-8907-f18d6ca1bf77)

If I dig in a bit further, we've tried to initialize a bunch of these TwoPhaseFilterMatchingDisiWrapper objects.
![image](https://github.com/user-attachments/assets/b2dec7b6-61e7-4cad-935f-45d1053e3df0)

In each of those we're initializing these 30MB byte arrays that are all 0's inside of the `ShapeDocValuesQuery` via a `Lucene90DocValuesProducer`:
![image](https://github.com/user-attachments/assets/6da233c6-ece5-44c2-9f08-b8a79f5a1252)

Notably, these byte arrays hav 30,462,618 entries. That's the same number as `val$entry.maxLength`:
![image](https://github.com/user-attachments/assets/68d61b30-cf79-44b4-b1c2-d90d659cbfcf)

What I think is happening:
For each bucket in the aggregation:
Create a [`ShapeDocValuesQuery`](https://github.com/elastic/elasticsearch/blob/v8.15.1/server/src/main/java/org/elasticsearch/lucene/spatial/ShapeDocValuesQuery.java)
During scoring in either `getContainsWeight` or `getStandardWeight` a  `Lucene90DocValuesProducer` is created via:  
 https://github.com/elastic/elasticsearch/blob/v8.15.1/server/src/main/java/org/elasticsearch/lucene/spatial/ShapeDocValuesQuery.java#L124-L127

That then creates an array in one of these spots: 

https://github.com/apache/lucene/blob/releases/lucene/9.11.1/lucene/core/src/java/org/apache/lucene/codecs/lucene90/Lucene90DocValuesProducer.java#L766-L766

https://github.com/apache/lucene/blob/releases/lucene/9.11.1/lucene/core/src/java/org/apache/lucene/codecs/lucene90/Lucene90DocValuesProducer.java#L807-L808

The size of that array is `maxLength` of the entry.
That max length is equal to the size of the largest value that might be read out of the index via the producer.

If you have a (large number of buckets * large geometry) you OOM. There's no protection (ex. raise an error if too much memory would be used) or safety (ex. allocate memory just-in-time/few buckets at a time). I would be satisfied to see either of these added. Even just a check that raises an error if more than some threshold of bytes will be allocated would be sufficient because I'd then be able to find problem data and re-index it in another form. As is I can't easily find what indices have these large geometries.
