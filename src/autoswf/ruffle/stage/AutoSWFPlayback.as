package {
    import flash.display.DisplayObjectContainer;
    import flash.display.MovieClip;
    import flash.events.Event;

    /** Pause and frame stepping (spec §5.6). Pausing stops every playing clip under the avatar (remembered) and holds
     *  the skeleton stand-in and the walk. The armor head's own ENTER_FRAME code keeps running, as it would in the
     *  game: it reacts to its clips' frames, which hold (Ruffle shares one enterFrame event among all objects, so
     *  stopping it for the head would stop it for the whole stage). One frame forward does what a frame does in Flash:
     *  the head's ENTER_FRAME, then the clips and the skeleton advance. One frame back replays what is playing from its
     *  start up to the previous frame (Flash cannot go backwards). */
    public class AutoSWFPlayback {
        public var paused:Boolean = false;
        /** Frames shown since the current animation started. */
        public var frame:int = 0;
        private var stageRef:AutoSWFStage;
        private var stopped:Array = [];

        public function AutoSWFPlayback(stageRef:AutoSWFStage) {
            this.stageRef = stageRef;
        }

        /** Called when an animation starts. */
        public function restarted():void {
            frame = 0;
        }

        /** Called on each ENTER_FRAME of the stage. */
        public function tick():void {
            if (!paused) frame++;
        }

        public function pause():void {
            if (paused) return;
            paused = true;
            stopped = [];
            collect(stageRef.avatar);
            stageRef.avatar.mcChar.paused = true;
        }

        public function resume():void {
            if (!paused) return;
            paused = false;
            for each (var clip:MovieClip in stopped) clip.play();
            stopped = [];
            stageRef.avatar.mcChar.paused = false;
        }

        /** One frame forward (1) or back (-1), paused. Back replays the animation and steps until the clip that shows
         *  it (the head's body clip, else the head) is one frame earlier than now. */
        public function step(by:int):void {
            if (!paused) pause();
            if (by >= 0) {
                forward();
                return;
            }
            var want:int = shownFrame() - 1;
            stageRef.replay();
            // the armor's code may leave a hold or a loop where it is (TheSwordHero does not restart Idle when it is
            // already on Idle): then the clip that shows it starts over by itself
            if (shownFrame() > Math.max(1, want)) restartShown();
            paused = false;
            pause();
            frame = 0;
            for (var i:int = 0; i < 1000 && shownFrame() < want; i++) forward();
        }

        /** The clip showing the animation goes back to its first frame, playing (so pause holds it). */
        private function restartShown():void {
            var face:MovieClip = stageRef.face;
            var body:MovieClip = face.getChildByName("body") as MovieClip;
            if (body != null) {
                body.gotoAndPlay(1);
                return;
            }
            var labels:Array = face.currentLabels.sortOn("frame", Array.NUMERIC);
            var start:int = 1;
            for each (var label:Object in labels) {
                if (label.frame <= face.currentFrame) start = label.frame;
            }
            face.gotoAndPlay(start);
        }

        /** The frame of the clip that shows the animation: the head's body clip (release-style armors), else the head. */
        public function shownFrame():int {
            var face:MovieClip = stageRef.face;
            if (face == null) return 0;
            var body:MovieClip = face.getChildByName("body") as MovieClip;
            return body != null ? body.currentFrame : face.currentFrame;
        }

        private function forward():void {
            if (stageRef.face != null) stageRef.face.dispatchEvent(new Event(Event.ENTER_FRAME));
            // clips the head's code made just now show their first frame on this one, as in Flash: collected after
            for each (var clip:MovieClip in stopped.concat()) {
                if (clip.currentFrame >= clip.totalFrames) clip.gotoAndStop(1);
                else clip.nextFrame();
            }
            stageRef.avatar.mcChar.advance();
            collect(stageRef.avatar);
            frame++;
        }

        /** Stop the playing clips under `container`, and remember them. */
        private function collect(container:DisplayObjectContainer):void {
            for (var i:int = 0; i < container.numChildren; i++) {
                var child:DisplayObjectContainer = container.getChildAt(i) as DisplayObjectContainer;
                if (child == null) continue;
                var clip:MovieClip = child as MovieClip;
                if (clip != null && clip.totalFrames > 1 && clip.isPlaying) {
                    clip.stop();
                    if (stopped.indexOf(clip) < 0) stopped.push(clip);
                }
                collect(child);
            }
        }
    }
}
