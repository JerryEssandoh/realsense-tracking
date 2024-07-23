#!/bin/bash
# exit when any command fails
set -e

# keep track of the last executed command
trap 'last_command=$current_command; current_command=$BASH_COMMAND' DEBUG
# echo an error message before exiting
trap 'echo "\"${last_command}\" command filed with exit code $?."' EXIT

SRC="."
DST_COMP="jakedev42_@172.30.60.117"
DST_FOLDER="/home/jakedev42_/ecalmeas"
file_name="$(basename -a $1)"
echo $file_name
echo "Attempting to copy data from $1 to $DST"
echo $1
scp -pr /home/a2sys/ecalmeas/$file_name $DST_COMP:$DST_FOLDER/$file_name
