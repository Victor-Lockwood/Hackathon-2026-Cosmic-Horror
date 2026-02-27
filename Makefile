.PHONY: help setup music docs

help:
	@echo ""
	@echo " Available make Commands"
	@echo "==============================="
	@echo ""
	@echo " setup:    Install/Update the required dependencies for the project."
	@echo " music:    Run the MIDI engine to generate music."
	@echo " docs:     Serve the documentation using Zensical."

setup:
	@conda env update --file environment.yml --prune
	@echo "Environment setup complete. To activate the environment, run: conda activate hackathon"

music:
	@python src/midi_engine.py

docs:
	@zensical serve
