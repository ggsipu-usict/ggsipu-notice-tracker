#!/usr/bin/bash

if git checkout heroku; then
    if git merge master; then
        git push heroku heroku:master
        heroku ps:scale worker=1
    fi
fi