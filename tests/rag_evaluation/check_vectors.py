import lancedb
import numpy as np

db = lancedb.connect('data/lancedb')
tbl = db.open_table('meeting_segments')

recs = tbl.search().to_list()
print(f"Total records: {len(recs)}\n")

# Check vector dimensions and data types
vectors = []
for i, rec in enumerate(recs):
    vec = np.array(rec['vector'])
    vectors.append(vec)
    print(f"Record {i}: shape={vec.shape}, dtype={vec.dtype}, sum={np.sum(vec):.2f}")

# Check if all vectors have same dimension
dims = [v.shape for v in vectors]
if len(set(dims)) > 1:
    print(f"\n⚠️  WARNING: Vector dimensionality is INCONSISTENT!")
    print(f"   Dimensions: {set(dims)}")
else:
    print(f"\n✓ All vectors have consistent dimension: {dims[0]}")

# Check vector norm (should be ~ standard)
norms = [np.linalg.norm(v) for v in vectors]
print(f"\nVector norms: min={min(norms):.2f}, max={max(norms):.2f}, mean={np.mean(norms):.2f}")

if max(norms) > 100 or min(norms) < 0.01:
    print(f"⚠️  WARNING: Unusual vector norms detected!")
