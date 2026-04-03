#ifndef PROGRAM_EXTERNALPLAYER_H_
#define PROGRAM_EXTERNALPLAYER_H_

#include <string>
#include <cstdio>
#include "../core/global.h"
#include "../core/logger.h"
#include "../game/board.h"

//Manages a GTP subprocess that acts as an external opponent in selfplay.
//One instance per game — spawn before the game, destroy after.
class ExternalPlayer {
public:
  ExternalPlayer(const std::string& command, Logger& logger);
  ~ExternalPlayer();

  ExternalPlayer(const ExternalPlayer&) = delete;
  ExternalPlayer& operator=(const ExternalPlayer&) = delete;

  //Set up a new game. Sends "boardsize" and "clear_board" to the subprocess.
  void newGame(int xSize, int ySize);

  //Ask the external player for a move. Sends "genmove <color>".
  //Returns a Loc on the board, or Board::NULL_LOC on failure.
  Loc getMove(Player pla, const Board& board);

  //Inform the external player of a move. Sends "play <color> <loc>".
  void playMove(Loc loc, Player pla, const Board& board);

  //Graceful shutdown.
  void close();

private:
  std::string command;
  Logger& logger;
  pid_t childPid;
  FILE* toChild;   //write commands here
  FILE* fromChild;  //read responses here
  bool alive;

  void startProcess();
  void stopProcess();

  //Send a GTP command, return (success, response_text).
  std::pair<bool, std::string> sendGTP(const std::string& cmd);

  static std::string playerToGTPColor(Player pla);
};

#endif  // PROGRAM_EXTERNALPLAYER_H_
