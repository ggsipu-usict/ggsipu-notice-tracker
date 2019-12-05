#!/usr/bin/bash

parent_dir=$(dirname $(pwd))
vsc_launch=".vscode/launch.json"



function set_env() {
    if [ -f $1 ]; then
        eval $(cat $vsc_launch | python -c 'import os,json,sys;envs=json.load(sys.stdin) \
            ["configurations"][1]["env"];print(*[f"export {k}=\"{v}\";" for k,v in envs.items()], sep="")')
        echo "[TEMP_ENVR] env loaded from ${1}." 
    else
        echo "[TEMP_ENVR] ${1} not found. No env loaded." 
    fi
}


function clean()
{
    rm -r $1
}

function setup()
{
    set_env $vsc_launch
    fname=$(basename $1)
    temp_dir="/tmp/${fname%.*}_tmp"
    mkdir -p $temp_dir

    cp $1 $temp_dir/

    cd $temp_dir
    chmod +x ${fname}

    echo "[TEMP_ENVR] ${fname} LAUNCH."
    ./${fname}
    echo "[TEMP_ENVR] Cleaning ${temp_dir}."
    clean $temp_dir
}



if [[ $# -gt 0 ]]; then
    setup $1
else
    echo "[TEMP_ENVR] No script passed."
fi

