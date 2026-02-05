import os
import json

def list_files(directory="."):
    """Lists all files recursively and formats them into the requested JSON structure."""
    file_list = []
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
            if file in ( "package.json", "ls_json.py"):
                continue
            
            # Get relative path
            rel_path = os.path.relpath(os.path.join(root, file), directory)
            # Use forward slashes for the URL format
            clean_path = rel_path.replace("\\", "/")
            
            file_list.append([clean_path, clean_path])
    
    # Sort the list alphabetically for better readability
    file_list.sort()
    
    return {
        "urls": file_list,
        "version": "1.0"
    }

if __name__ == "__main__":
    output = list_files()
    print(json.dumps(output, indent=4))
