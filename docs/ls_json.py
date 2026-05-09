import os
import json
import hashlib

def get_md5_of_file(file_path):
    # Create an MD5 hash object
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        # Read the file in chunks and update the hash object
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
            return hash_md5.hexdigest()

def list_files(directory="."):
    """Lists all files recursively and formats them into the requested JSON structure."""
    file_list = []
    nfiles = []
    for root, dirs, files in os.walk(directory):
        # Filter out hidden directories (like .git, .gemini, brain etc.)
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        # Also filter out the brain/folder to keep the list clean if requested
        if 'brain' in dirs:
            dirs.remove('brain')
            
        for file in files:
            # Skip hidden files
            if file.startswith('.'):
                continue
            if file in ( "package.json", "ls_json.py", "postprocess.sh"):
                continue
            
            # Get relative path
            rel_path = os.path.relpath(os.path.join(root, file), directory)
            # Use forward slashes for the URL format
            clean_path = rel_path.replace("\\", "/")
            
            file_list.append([clean_path, clean_path])
            nfiles.append(
                {
                    'path' : clean_path,
                    'md5' : get_md5_of_file(rel_path)
                }
                )
    
    # Sort the list alphabetically for better readability
    file_list.sort()

    return {
        "urls": file_list,
        "files" : nfiles,
        "version": "1.0"
    }

if __name__ == "__main__":
    output = list_files()
    print(json.dumps(output, indent=4))
