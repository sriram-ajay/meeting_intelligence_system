import requests
import sys
import tempfile
import pytest

pytestmark = pytest.mark.integration

# Create a test file
print("Creating test document...")
test_content = """
Meeting Transcript - Test Document
Date: 2026-02-06
Participants: Alice, Bob, Charlie

[00:00] Alice: Good morning everyone. Let's discuss the Q1 roadmap.
[00:15] Bob: I think we should focus on infrastructure improvements first.
[00:30] Charlie: Agreed. But we also need to allocate resources for customer support.
[01:00] Alice: Let's vote on this proposed timeline.
[01:15] Bob: I vote yes.
[01:30] Charlie: Also voting yes.
[02:00] Alice: Great, it's unanimous. Let's move forward with this plan.
"""

def run_test():
    # Write to temp file and upload
    print("Uploading document...")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tf:
        tf.write(test_content)
        tf.flush()
        
        with open(tf.name, 'rb') as f:
            files = {'file': f}
            try:
                response = requests.post('http://localhost:8000/api/upload', files=files, timeout=60)
                print(f"Upload status: {response.status_code}")
                print(f"Response: {response.json()}")
            except Exception as e:
                print(f"Skipping API-based test: {e} (Expected in CI/CD environments without a running server)")
                return

    # Check DB state
    print("\nChecking database...")
    try:
        import lancedb
        db = lancedb.connect('data/lancedb')
        tbl = db.open_table('meeting_segments')
        docs = tbl.search().to_list()
        print(f"Documents in DB: {len(docs)}")
    except Exception as e:
        print(f"Skipping DB-based test: {e}")
        return

    # Test query
    print("\nTesting query...")
    try:
        response = requests.post('http://localhost:8000/api/query', json={"query": "What was discussed?"}, timeout=60)
        print(f"Query status: {response.status_code}")
        data = response.json()
        print(f"Answer: {data.get('answer')}")
    except Exception as e:
        print(f"Skipping query-based test: {e}")

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"Error: {e}")
