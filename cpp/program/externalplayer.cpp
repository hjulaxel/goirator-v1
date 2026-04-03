#include "../program/externalplayer.h"

#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <sys/wait.h>

using namespace std;

ExternalPlayer::ExternalPlayer(const string& cmd, Logger& log)
  : command(cmd), logger(log), childPid(-1), toChild(nullptr), fromChild(nullptr), alive(false)
{
  startProcess();
}

ExternalPlayer::~ExternalPlayer() {
  close();
}

void ExternalPlayer::startProcess() {
  int stdinPipe[2];
  int stdoutPipe[2];

  if(pipe(stdinPipe) != 0 || pipe(stdoutPipe) != 0)
    throw StringError("ExternalPlayer: pipe() failed");

  pid_t pid = fork();
  if(pid < 0)
    throw StringError("ExternalPlayer: fork() failed");

  if(pid == 0) {
    //Child process
    ::close(stdinPipe[1]);
    ::close(stdoutPipe[0]);
    dup2(stdinPipe[0], STDIN_FILENO);
    dup2(stdoutPipe[1], STDOUT_FILENO);
    //Redirect stderr to /dev/null to keep it clean
    int devnull = open("/dev/null", O_WRONLY);
    if(devnull >= 0) { dup2(devnull, STDERR_FILENO); ::close(devnull); }
    ::close(stdinPipe[0]);
    ::close(stdoutPipe[1]);
    execl("/bin/sh", "sh", "-c", command.c_str(), (char*)nullptr);
    _exit(127);
  }

  //Parent process
  ::close(stdinPipe[0]);
  ::close(stdoutPipe[1]);

  toChild = fdopen(stdinPipe[1], "w");
  fromChild = fdopen(stdoutPipe[0], "r");

  if(toChild == nullptr || fromChild == nullptr)
    throw StringError("ExternalPlayer: fdopen() failed");

  childPid = pid;
  alive = true;

  logger.write("ExternalPlayer: started subprocess (pid " + Global::intToString(childPid) + "): " + command);
}

void ExternalPlayer::stopProcess() {
  if(!alive)
    return;
  alive = false;

  if(toChild != nullptr) {
    fprintf(toChild, "quit\n");
    fflush(toChild);
    fclose(toChild);
    toChild = nullptr;
  }
  if(fromChild != nullptr) {
    fclose(fromChild);
    fromChild = nullptr;
  }

  if(childPid > 0) {
    int status;
    //Give it a moment to exit gracefully, then force kill
    usleep(100000); //100ms
    if(waitpid(childPid, &status, WNOHANG) == 0) {
      kill(childPid, SIGTERM);
      usleep(200000);
      if(waitpid(childPid, &status, WNOHANG) == 0) {
        kill(childPid, SIGKILL);
        waitpid(childPid, &status, 0);
      }
    }
    childPid = -1;
  }
}

void ExternalPlayer::close() {
  stopProcess();
}

pair<bool, string> ExternalPlayer::sendGTP(const string& cmd) {
  if(!alive)
    return make_pair(false, "process not alive");

  fprintf(toChild, "%s\n", cmd.c_str());
  fflush(toChild);

  string response;
  char buf[4096];
  bool gotContent = false;

  while(true) {
    if(fgets(buf, sizeof(buf), fromChild) == nullptr) {
      alive = false;
      return make_pair(false, "EOF from external player");
    }
    string line(buf);
    //Strip trailing newline
    while(!line.empty() && (line.back() == '\n' || line.back() == '\r'))
      line.pop_back();

    if(line.empty() && gotContent)
      break; //Blank line after content = end of GTP response
    if(!line.empty()) {
      gotContent = true;
      response = line;
    }
  }

  if(response.size() >= 2 && response[0] == '=') {
    string text = response.substr(1);
    text = Global::trim(text);
    return make_pair(true, text);
  }
  if(response.size() >= 2 && response[0] == '?') {
    string text = response.substr(1);
    text = Global::trim(text);
    return make_pair(false, text);
  }
  return make_pair(true, response);
}

string ExternalPlayer::playerToGTPColor(Player pla) {
  return pla == P_BLACK ? "B" : "W";
}

void ExternalPlayer::newGame(int xSize, int ySize) {
  if(xSize != ySize) {
    auto result = sendGTP("rectangular_boardsize " + Global::intToString(xSize) + " " + Global::intToString(ySize));
    if(!result.first)
      logger.write("ExternalPlayer: rectangular_boardsize failed: " + result.second);
  }
  else {
    auto result = sendGTP("boardsize " + Global::intToString(xSize));
    if(!result.first)
      logger.write("ExternalPlayer: boardsize failed: " + result.second);
  }
  auto result = sendGTP("clear_board");
  if(!result.first)
    logger.write("ExternalPlayer: clear_board failed: " + result.second);
}

Loc ExternalPlayer::getMove(Player pla, const Board& board) {
  string cmd = "genmove " + playerToGTPColor(pla);
  auto result = sendGTP(cmd);

  if(!result.first) {
    logger.write("ExternalPlayer: genmove failed: " + result.second);
    return Board::NULL_LOC;
  }

  string moveStr = Global::trim(Global::toLower(result.second));
  if(moveStr == "resign" || moveStr == "pass")
    return Board::PASS_LOC;

  Loc loc;
  bool ok = Location::tryOfString(result.second, board, loc);
  if(!ok) {
    logger.write("ExternalPlayer: could not parse move: " + result.second);
    return Board::NULL_LOC;
  }
  return loc;
}

void ExternalPlayer::playMove(Loc loc, Player pla, const Board& board) {
  string locStr;
  if(loc == Board::PASS_LOC)
    locStr = "pass";
  else
    locStr = Location::toString(loc, board);

  string cmd = "play " + playerToGTPColor(pla) + " " + locStr;
  auto result = sendGTP(cmd);
  if(!result.first)
    logger.write("ExternalPlayer: play failed: " + result.second);
}
