# System imports
import cgi
import configparser as cp
from ftplib import FTP
import glob as gb
import os
import pwd
import shutil as su
import sys
import tarfile
import time
from typing import List
from urllib.request import urlopen
from urllib.request import urlretrieve

from src.modules import Result


class init(object):
    def __init__(self, glob):
        self.glob = glob

    # Read non-cfg file into list
    def read(self, file_path):
        if not os.path.isfile(file_path):
            self.glob.lib.msg.error("File " + self.glob.lib.rel_path(file_path) + " not found.")

        with open(file_path) as fp:
            return fp.readlines()

    # Delete tmp build files if installation fails
    def cleanup(self, clean_list):
        
        # Clean default *.tmp files
        if not clean_list:
            clean_list = gb.glob(os.path.join(self.glob.ev['BP_HOME'], 'tmp.*'))

        if clean_list:
            for f in clean_list:
                try:
                    # Files
                    if os.path.isfile(f):
                        os.remove(f)
                    # Clean dir trees
                    elif os.path.isdir(f):
                        self.prune_tree(f)

                    self.glob.lib.msg.log("Successfully removed tmp object " + self.glob.lib.rel_path(f))
                except Exception as e :
                    self.glob.lib.msg.log("Failed to remove tmp object " + self.glob.lib.rel_path(f))

    # Remove created files if we are crashing
    def rollback(self):
        # Clean tmp files
        self.cleanup([])
        # Clean 
        self.cleanup(self.glob.cleanup)

    # Find file in directory
    def find_exact(self, filename, path):
        # Check file doesn't exist already
        if os.path.isfile(filename):
            return filename

        # Search recursively for file
        files = gb.glob(path+'/**/'+filename, recursive = True)

        if files:
            return files[0]
        else:
            return None

    # Confirm file exists
    def exists(self, fileName, path):

        if self.find_exact(fileName, path):
            return True
        else:
            return False

    # Looks for file in paths
    def look(self, paths, filename):

        if not filename:
            return False
        results = []
        for path in paths:
            found = gb.glob(os.path.join(path, filename)) 
            if found:
                results += found

        # Found one result
        if len(results) == 1:
            return results[0]

        # Didn't
        return False

    # Accepts list of paths and filename, returns file path to file if found, or errors 
    def find_in(self, paths, filename, error_if_missing):


        if os.path.isfile(filename):
            return filename

        # Add some default locations to the search path list
        paths.extend(["/", "", self.glob.ev['BP_HOME'], self.glob.cwd, self.glob.home])

        file_path = self.look(paths, filename) 

        if file_path:
            return file_path

        # Error if not found?
        if error_if_missing:

            self.glob.lib.msg.error(["Unable to locate file '" + filename + "' in any of these locations:"] +\
                                    [self.glob.lib.rel_path(p) for p in paths])

        return False

    # Find *file* in directory
    def find_partial(self, filename, path_list):
        # Check file doesn't exist already
        if os.path.isfile(filename):
            return filename
        # Iterate input list
        for path in path_list:
        # Search provided path for file
            for root, dirs, files in os.walk(path):
                match = next((s for s in files if filename in s), None)
                if match:
                    return os.path.join(root, match)

        # File not found
        return None

    # Get owner of file
    def file_owner(self, filename):
        return pwd.getpwuid(os.stat(filename).st_uid).pw_name

    # Check write permissions to a directory
    def write_permission(self, path):
        if os.access(path, os.W_OK):
            return True
        return False


    # Get a list of sub-directories, including full path
    def get_subdirs_path(self, base):
        try:
            return [os.path.join(base, sub) for sub in os.listdir(base)
                if os.path.isdir(os.path.join(base, sub))]
        except Exception as e:
            self.glob.lib.msg.error("Directory '" + base + "' not found, did you run --validate?")        

    # Get a list of sub-directories, called by 'search_tree'
    def get_subdirs(self, base):
        try:
            return [sub for sub in os.listdir(base)
                if os.path.isdir(os.path.join(base, sub))]
        except Exception as e:
            self.glob.lib.msg.error("Directory '" + base + "' not found, did you run --validate?")

    # Recursive function to scan app directory, called by 'get_installed'
    def search_tree(self, installed_list, app_dir, start_depth, current_depth, max_depth):
        for d in self.get_subdirs(app_dir):
            if d != self.glob.stg['module_dir']:
                new_dir = os.path.join(app_dir, d)
                # Once tree hits max search depth, append path to list
                if current_depth == max_depth:
                    installed_list += [new_dir]
                # Else continue to search tree
                else:
                    self.search_tree(installed_list, new_dir, start_depth,current_depth + 1, max_depth)

    # Prune dir tree until not unique or hit system dir
    def prune_tree(self, path: str) -> None:
        path_elems  = path.split(self.glob.stg['sl'])
        parent_path = self.glob.stg['sl'].join(path.split(self.glob.stg['sl'])[:-1])
        parent_dir  = path_elems[-2]

        # If parent dir is root ('build' or 'modulefile') or if it contains more than this subdir, delete this subdir
        if (parent_dir == self.glob.stg['build_topdir']) or \
           (parent_dir == self.glob.stg['module_dir']) or \
           (parent_dir == os.path.basename(self.glob.ev['BPS_COLLECT'])) or \
           (len(gb.glob(os.path.join(parent_path,"*"))) > 1):

            try:     
                su.rmtree(path)
            except OSError as err:
                print(err)
                self.glob.lib.msg.exit("Can't delete: " + self.glob.lib.rel_path(path))
        # Else resurse with parent
        else:
            self.prune_tree(parent_path)

    # Create directories if needed
    def create_dir(self, path):
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except:
                self.glob.lib.msg.error(
                    "Failed to create directory " + path)

        # Add to cleanup list
        self.glob.cleanup.append(path)


    # Delete directory after user prompt
    def purge_dir(self, path):

        if os.path.isdir(path):
            self.glob.lib.msg.high("Delete " + path + " ?")
            self.glob.lib.msg.prompt()
            su.rmtree(path)
            print("Done.\n")

        else:
            self.glob.lib.msg.high("Skipping " + path + ": does not exist.")



    # Get list of files in search path
    def get_files_in_path(self, search_path):
        return gb.glob(os.path.join(search_path, "*.cfg"))

    # Check if path exists, if so append .dup
    def check_dup_path(self, path):
        if os.path.isdir(path):
            return self.check_dup_path(path + ".dup")
        return path

    # Copy tmp files to directory
    def copy(self, dest, src, new_name=None, clean=None):

        # Get file name
        if not new_name:
            new_name = src
            if self.glob.stg['sl'] in new_name:
                new_name = new_name.split(self.glob.stg['sl'])[-1]

            # Strip tmp prefix from file for new filename
            if 'tmp.' in new_name:
                new_name = new_name[4:]

        try:
            if os.path.isfile(src):
                su.copyfile(src, os.path.join(dest, new_name))
            else:
                su.copytree(src, os.path.join(dest, new_name))
            self.glob.lib.msg.log("Copied " + src + " into " + dest)
        except IOError as e:
            self.glob.lib.msg.high(e)
            self.glob.lib.msg.error(
                "Failed to move " + src + " to " + os.path.join(dest, new_name))

        # Remove tmp files after copy
        if clean:
            os.remove(src)

    # Extract tar file list to working dir
    def untar_file(self, src):

        # untar now
        if self.glob.stg['sync_staging']:
            self.glob.lib.msg.low("Extracting " + src + "...")

            # File not found
            if not os.path.isfile(src):
                self.glob.lib.msg.error("Input file '" + src + "' not found in repo " + \
                                        self.glob.lib.rel_path(self.glob.ev['BP_REPO']))

            # Extract to working dir
            tar = tarfile.open(src)
            tar.extractall(self.glob.config['metadata']['copy_path'])
            tar.close()

        # untar in script
        else:
            self.glob.stage_ops.append("tar -xf " + src + " -C ${copy_path}")

    # Copy file to working dir
    def cp_file(self, src):

        # Absolute path or in local repo
        src_path = os.path.expandvars(src)
        if not os.path.isfile(src_path) and not os.path.isdir(src_path):
            src_path = os.path.join(self.glob.ev['BP_REPO'], src)

        # Copy now
        if self.glob.stg['sync_staging']:


            # Check presence
            if not os.path.isfile(src_path) and not os.path.isdir(src_path):
                self.glob.lib.msg.error("Input file '" + src + "' not found in repo " + \
                                        self.glob.lib.rel_path(self.glob.ev['BP_REPO']))

            self.glob.lib.msg.low("Copying " + src_path + "...")
            # Copy file
            if os.path.isfile(src_path):
                su.copy(src_path, self.glob.config['metadata']['copy_path'])

            # Copy dir
            else:
                dest = src_path.split(self.glob.stg['sl'])[-1]
                su.copytree(src_path, os.path.join(self.glob.config['metadata']['copy_path'], dest))

        # Copy in script
        else:
           self.glob.stage_ops.append("cp -r " + src_path + " " + self.glob.config['metadata']['copy_path']) 

    # Process local file depending on type
    def prep_local(self, file_list):

        for filename in file_list:

            filename  = filename.strip()
            self.glob.lib.msg.log("Staging local file " + filename)

            ## Locate file
            #if self.glob.stg['sync_staging']:
            #    file_path = self.find_in([self.glob.ev['BP_REPO'], self.glob.config['metadata']['copy_path']], filename, True)
            # Assume will be in repo after download
            #else:
            file_path = os.path.join(self.glob.ev['BP_REPO'], filename)

            # Add tar op to staged ops
            #if any(x in filename for x in ['tar', 'tgz', 'bgz']):
            if self.glob.stg['soft_links']:
                self.glob.stage_ops.append("stage -ln " + file_name)
            else:
                self.glob.stage_ops.append("stage " + file_name)
            # Add cp op to staged ops
            #else:
            #    self.glob.stage_ops.append("cp -r " + file_path + " ${working_path}")

    def stage_local(self, file_path):

        # Check if compressed
            if any(x in filename for x in ['tar', 'tgz', 'bgz']):
                self.untar_file(file_path)
            else:
                self.cp_file(file_path)

    def get_ftp_server(self, url):
        return "ftp." + url.split("ftp.")[1].split("/")[0]

    # Extract filename from URL 
    def get_url_filename(self, url):

        # Test if URL is FTP
        if "ftp" in url:

            try:
                # Check server is reachable
                ftp = FTP(self.get_ftp_server(url))
                ftp.login()

            except Exception as e:
                print(e)
                self.glob.lib.msg.error("Unable to reach URL " + url)

            # Return filename 
            return url.split("/")[-1]

        # Assume HTTP
        else:

            retries = 0
            while retries < 3:

                try:
                    remotefile = urlopen(url)
                    value, params = cgi.parse_header(remotefile.info()['Content-Disposition'])
                    return params["filename"]
                except:
                    pass
                
                self.glob.lib.msg.warn("Retrying URL...")
                time.sleep(2)
                retries += 1

            # Failed to query URL after 3 tries
            self.glob.lib.msg.error("Unable to reach URL " + url)

    # Check if file or dir is present in local repo
    def in_local_repo(self, filename):

        if os.path.isfile(os.path.join(self.glob.ev['BP_REPO'], filename)) \
        or os.path.isdir(os.path.join(self.glob.ev['BP_REPO'], filename)):
            return True
        return False

    # Download URL 
    def wget_file(self, url, filename):
        dest = None
        # Destination = working_dir or local repo
        if self.glob.stg['cache_downloads']:
            dest = os.path.join(self.glob.ev['BP_REPO'], filename)
        else:
            dest = os.path.join(self.glob.config['metadata']['copy_path'], filename)

        # Download now
        if self.glob.stg['sync_staging']:
            try:
                self.glob.lib.msg.low("Fetching file " + filename + "...")
                urlretrieve(url, dest)
            except Exception as e:
                self.glob.lib.msg.error("Failed to download URL '" + url + "'")
        # Download in script
        else:
            self.glob.stage_ops.append("wget -O " + dest + " " + url)

    # Download list of URLs
    def prep_urls(self, url_list):
        for url in url_list:
            local_copy = False
            # Clean up list elem
            url = url.strip()
            self.glob.lib.msg.log("Staging URL: " + str(url))

            # Get filename from URL
            filename = self.get_url_filename(url)

            # Prefer local files & file in local repo
            if self.glob.stg['prefer_local_files'] and self.in_local_repo(filename):
                self.glob.lib.msg.low("Using " + filename + " located in " + self.glob.stg['local_repo_env'])
                local_copy = True

            # No local copy - download
            if not local_copy:
                self.glob.lib.msg.low("Collecting " + filename)
                self.wget_file(url, filename)
            
            # Process downloaded file
            self.prep_local([filename])


    # Stage files listed in cfg under [files]
    def stage(self):
      
        # Create working dir
        #self.create_dir(self.glob.config['metadata']['copy_path'])

        # Check section exists
        if 'files' in self.glob.config.keys():

            self.glob.lib.msg.low("Staging input files...")

            # Evaluate expressions in [config] and [files] sections of cfg file 
            self.glob.lib.expr.eval_dict(self.glob.config['config'], False)
            self.glob.lib.expr.eval_dict(self.glob.config['files'], False)

            # Parse through supported file operations - local, download
            for op in self.glob.config['files'].keys():

                assets = self.glob.config['files'][op].split(',')

                # Symlink assets
                if self.glob.stg['soft_links']:
                    [self.glob.stage_ops.append("stage -ln " + asset) for asset in assets]
                else:
                    [self.glob.stage_ops.append("stage " + asset) for asset in assets]


#                # Copy local file [from BP_REPO or local path]
#                if op == 'local':
#                    self.prep_local(self.glob.config['files'][op].split(','))
#                # Download generic URL
#                elif op == 'download':
#                    self.prep_urls(self.glob.config['files'][op].split(','))
#                # Download from gdrive with API
#                elif op == 'gdrive'
#                    self.prep_gdrive(self.glob.config['files'][op].split(','))
#                else:
#                    self.glob.lib.msg.error(["Unsupported file stage operation selected: '" + op + "'.", 
#                                            "Supported operations = 'download' or 'local'"])

    # Write module to file
    def write_list_to_file(self, list_obj, output_file):
        with open(output_file, "w") as fp:
            for line in list_obj:
                fp.write(line)

    # Write command line to history file
    def write_cmd_history(self):
        history_file = os.path.join(self.glob.ev['BP_HOME'], ".history")
        with open(history_file, "a") as hist:
            hist.write(self.glob.lib.misc.get_input_str() + "\n")

    # Get list of config files by type
    def get_cfg_list(self, cfg_type):
        # Get cfg subdir name from input
        search_path_list = None
        cfg_list = [] 
        if cfg_type == "build":
            search_path_list = self.glob.stg['build_cfg_path']
        elif cfg_type == "bench":
            search_path_list = self.glob.stg['bench_cfg_path']
        else:
            self.glob.lib.msg.error("unknown cfg type '"+cfg_type+"'. get_cfgs() accepts either 'build' or 'bench'.")

        # Look for cfg files in each search path
        for search_path in search_path_list:
            # Get list of cfg files in dir
            cfg_list = self.glob.lib.files.get_files_in_path(search_path)

            # If system subdir exists, scan that too
            if os.path.isdir(os.path.join(search_path,self.glob.system['system'])):
                cfg_list = cfg_list + self.glob.lib.files.get_files_in_path(os.path.join(search_path,self.glob.system['system']))

        return cfg_list

    # Parse cfg file into dict
    def read_cfg(self, cfg_file):
        cfg_parser = cp.ConfigParser()
        cfg_parser.optionxform=str
        cfg_parser.read(cfg_file)


        if not os.path.isfile(cfg_file):
            self.glob.lib.msg.error("Unable to read cfg file " + self.glob.lib.rel_path(cfg_file))

        # Add file name & label to dict
        cfg_dict = {}
        cfg_dict['metadata'] ={}

        cfg_dict['metadata']['cfg_label'] = ".".join(cfg_file.split(self.glob.stg['sl'])[-1].split(".")[:-1])
        cfg_dict['metadata']['cfg_file']  = cfg_file

        # Read sections into dict
        for section in cfg_parser.sections():
            cfg_dict[section] = dict(cfg_parser.items(section))

        return cfg_dict

    # Delete all user files
    def purge(self):
        if self.glob.args.purge:
            purge_paths = [ self.glob.ev['BP_HOME'],
                            self.glob.ev['BP_APPS'],
                            self.glob.ev['BP_RESULTS']]

            # Purge MUST be interactive
            self.glob.stg['interactive'] = True

            # clean up
            for path in purge_paths:
                self.purge_dir(path)

            sys.exit(0)


    # Move benchmark directory from complete to captured/failed, once processed
    def move_to_archive(self, result_path: str, dest: str):
        if not os.path.isdir(result_path):
            self.glob.lib.msg.error("result directory '" + self.glob.lib.rel_path(result_path) + "' not found.")

        # Move to archive
        try:
            su.move(result_path, dest)
        # If folder exists, rename and try again
        except:
            self.glob.lib.msg.warn("Result directory already exists in archive. Appending suffix .dup")
            # Rename result dir
            su.move(result_path, result_path + ".dup")
            # Try again
            self.move_to_archive(result_path + ".dup", dest)


    def copy_prov_data(self, record: Result, dest_dir: str):#file_list: List[str], src: str, dest: str) -> None:

        if self.glob.stg['file_copy_handler'] == "cp":
            if not self.glob.ev['BPS_COLLECT']:
                self.glob.lib.msg.error("$BPS_COLLECT not set!")

            # Check write permissions
            if not self.glob.lib.files.write_permission(self.glob.ev['BPS_COLLECT']):
                self.glob.lib.msg.error("Unable to write to " + self.glob.ev['BPS_COLLECT'])

            # File destination
            dest_path = os.path.join(self.glob.ev['BPS_COLLECT'], dest_dir)

            self.glob.lib.files.create_dir(dest_path)

            # Copy files to local directory
            #self.glob.lib.files.copy(dest_path, self.output_path)

            move_list = []
            # First file to copy = user ouput file
            if record.result['output_file']:
                move_list.append(os.path.join(record.path, record.result['output_file']))

            # Add standard files extentions
            search_substrings = ["*.err", "*.out", "*.sched", "*.job", "*.txt", "*.log"]
            for substring in search_substrings:
                matching_files = gb.glob(os.path.join(record.path, substring))
                move_list.extend(matching_files)

            # Add folders
            for directory in ["bench_files", "hw_report"]:
                path = os.path.join(record.path, directory)
                if os.path.isdir(path):
                    move_list.append(path)

            # Remove duplicates
            move_list = [*set(move_list)]

            # Copy
            for src in move_list:
                self.copy(dest_path, src)


    # Return timestamp from file
    def get_timestamp(self, keyword: str, search_file: str) -> str:

        # Search for item line and return in
        for line in search_file:
            if line.startswith(keyword):
                return line

        # Time line not found
        return None


    def cache(self, record: Result) -> None:

        # Only cache completed benchmarks
        if record.complete:
            cache_file = os.path.join(record.path, ".cache")

            # Don't cache twice
            if os.path.isfile(cache_file):
                return

            self.glob.lib.msg.log("Caching '" + str(record.value) + "' to " + cache_file)
            with open(cache_file, "a") as fp:
                fp.write("status = " + str(record.status) + "\n")
                fp.write("result = " + str(record.value) + "\n")


    def read_cache(self, cache_path: str, key: str) -> None:
        cache_file = os.path.join(cache_path, ".cache")
        if os.path.isfile(cache_file):
            cache = self.read(cache_file)
            for line in cache:
                if line.startswith(key):
                    value = line.split("=")[1].strip()
                    try:
                        value = float(value)
                        return value
                    except:
                        return value
        return None


    # Read result from .cache
    def decache_result(self, path: str) -> float:
        result = self.read_cache(path, "result")
        # Cast to float
        try:
            result = float(result)
        except:
            return None

        # Result != 0.0
        if result:
            self.glob.lib.msg.log("Read " + str(result) + " from " + path)
            return result

        self.glob.lib.msg.log("No cached result in " + path)
        return None

    # Read status from .cache
    def decache_status(self, path:str) -> str:
        status = self.read_cache(path, "status")
        self.glob.lib.msg.log("Read " + str(status) + " from " + path)
        return status

    # Remove directory
    def delete_dir(self, path: str) -> None:

        if not os.path.isdir(path):
            self.glob.lib.msg.error("Cannot remove path " + self.glob.lib.rel_path(path) + ": does not exist.")
        self.glob.lib.msg.log("Removing " + path)
        try:
            su.rmtree(path)
        except OSError as err:
            print(err)
            self.glob.lib.msg.exit("Can't delete: " + self.glob.lib.rel_path(path))

	# Remove file
    def delete_file(self, file: str) -> None:
        if not os.path.isfile(file):
            self.glob.lib.msg.error("Cannot remove file " + self.glob.lib.rel_path(file) + ": does not exist.")
        self.glob.lib.msg.log("Removing " + file)
        try:
            os.remove(file)
        except OSError as err:
            print(err)
            self.glob.lib.msg.exit("Can't delete: " + self.glob.lib.rel_path(file))

