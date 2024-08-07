#!/bin/bash
# exit when any command fails
set -e

# keep track of the last executed command
trap 'last_command=$current_command; current_command=$BASH_COMMAND' DEBUG
# echo an error message before exiting
trap 'echo "\"${last_command}\" command filed with exit code $?."' EXIT

SRC="."
DST_COMP="jakedev42_@172.30.60.117"
DST_FOLDER="/home/jakedev42_/realsense-tracking"
DST="$DST_COMP:$DST_FOLDER"
echo "Attempting to sync $SRC with $DST"
rsync -avz --include='**.gitignore' --filter='dir-merge,-n /.gitignore' $SRC $DST
# rsync -avz --filter=':- .gitignore' $SRC $DST


# rsync -ah --delete 
#     --include .git --exclude-from="$(git -C $SRC ls-files \
#         --exclude-standard -oi --directory >.git/ignores.tmp && \
#         echo .git/ignores.tmp')" \
#     $SRC $DST 
